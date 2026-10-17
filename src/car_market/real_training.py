from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import ExtraTreesRegressor
from sklearn.impute import SimpleImputer
from sklearn.model_selection import KFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

from .model import CATEGORICAL, NUMERIC, ModelBundle, _regression_metrics, build_features


def _key(make: object, model: object) -> str:
    return f"{make}\x1f{model}"


def _summaries(frame: pd.DataFrame) -> tuple[dict[str, int], dict[str, float], dict[str, float], float]:
    groups = frame.groupby(["make", "model"])["asking_price"]
    support = {_key(make, model): int(value) for (make, model), value in groups.size().items()}
    medians = {_key(make, model): float(value) for (make, model), value in groups.median().items()}
    make_medians = {str(make): float(value) for make, value in frame.groupby("make")["asking_price"].median().items()}
    return support, medians, make_medians, float(frame["asking_price"].median())


def _fallback_predictions(train: pd.DataFrame, validation: pd.DataFrame, predictions: np.ndarray, threshold: int) -> np.ndarray:
    support, medians, make_medians, global_median = _summaries(train)
    adjusted = predictions.copy()
    for position, row in enumerate(validation.itertuples(index=False)):
        group_key = _key(row.make, row.model)
        count = support.get(group_key, 0)
        fallback = medians.get(group_key, make_medians.get(str(row.make), global_median))
        model_weight = min(count / threshold, 1.0)
        adjusted[position] = model_weight * predictions[position] + (1 - model_weight) * fallback
    return adjusted


def _real_pipeline(random_seed: int) -> Pipeline:
    categorical = Pipeline([
        ("imputer", SimpleImputer(strategy="most_frequent")),
        ("encoder", OneHotEncoder(handle_unknown="ignore", min_frequency=2)),
    ])
    processor = ColumnTransformer([
        ("categorical", categorical, CATEGORICAL),
        ("numeric", SimpleImputer(strategy="median"), NUMERIC),
    ])
    model = ExtraTreesRegressor(
        n_estimators=350,
        min_samples_leaf=2,
        max_features=0.8,
        n_jobs=-1,
        random_state=random_seed,
    )
    return Pipeline([("features", processor), ("model", model)])


def _extended_metrics(target: np.ndarray, prediction: np.ndarray) -> dict[str, float]:
    result = _regression_metrics(target, prediction)
    absolute_percentage = np.abs(target - prediction) / np.maximum(np.abs(target), 1.0)
    result["median_ape"] = round(float(np.median(absolute_percentage)), 4)
    result["wmape"] = round(float(np.sum(np.abs(target - prediction)) / np.sum(np.abs(target))), 4)
    return result


@dataclass
class RealModelBundle(ModelBundle):
    exact_support: dict[str, int] = field(default_factory=dict)
    exact_medians: dict[str, float] = field(default_factory=dict)
    make_medians: dict[str, float] = field(default_factory=dict)
    global_median: float = 0.0
    fallback_threshold: int = 5

    def support_count(self, row: dict) -> int:
        return self.exact_support.get(_key(row["make"], row["model"]), 0)

    def predict(self, frame: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        point = np.exp(self.point_model.predict(build_features(frame)))
        lower = point * np.exp(-self.conformal_margin_log)
        upper = point * np.exp(self.conformal_margin_log)
        for position, row in enumerate(frame.itertuples(index=False)):
            group_key = _key(row.make, row.model)
            support = self.exact_support.get(group_key, 0)
            fallback = self.exact_medians.get(
                group_key, self.make_medians.get(str(row.make), self.global_median)
            )
            weight = min(support / self.fallback_threshold, 1.0)
            point[position] = weight * point[position] + (1 - weight) * fallback
            uncertainty = (1 - min(support / 10, 1.0)) * 0.30
            lower[position] = min(lower[position] * np.exp(-uncertainty), point[position])
            upper[position] = max(upper[position] * np.exp(uncertainty), point[position])
        return point, lower, upper


def train_real_model(
    listings: pd.DataFrame,
    transaction_to_ask_ratio: float = 0.97,
    random_seed: int = 42,
    folds: int = 5,
    fallback_threshold: int = 5,
) -> RealModelBundle:
    if len(listings) < 100:
        raise ValueError("At least 100 real clean listings are required")
    data = listings.sample(frac=1, random_state=random_seed).reset_index(drop=True)
    target = data["asking_price"].to_numpy(dtype=float)
    oof_point = np.zeros(len(data))
    oof_baseline = np.zeros(len(data))
    fold_metrics: list[dict[str, Any]] = []
    splitter = KFold(n_splits=folds, shuffle=True, random_state=random_seed)

    for fold_number, (train_index, validation_index) in enumerate(splitter.split(data), start=1):
        train = data.iloc[train_index]
        validation = data.iloc[validation_index]
        x_train = build_features(train)
        x_validation = build_features(validation)
        y_train_log = np.log(train["asking_price"].to_numpy(dtype=float))
        point_model = _real_pipeline(random_seed + fold_number).fit(x_train, y_train_log)
        raw_prediction = np.exp(point_model.predict(x_validation))
        prediction = _fallback_predictions(train, validation, raw_prediction, fallback_threshold)
        oof_point[validation_index] = prediction

        support, medians, make_medians, global_median = _summaries(train)
        baseline = []
        for row in validation.itertuples(index=False):
            baseline.append(medians.get(_key(row.make, row.model), make_medians.get(str(row.make), global_median)))
        oof_baseline[validation_index] = baseline
        fold_metrics.append({
            "fold": fold_number,
            "train_rows": len(train),
            "validation_rows": len(validation),
            **_extended_metrics(validation["asking_price"].to_numpy(), prediction),
        })

    target_log = np.log(target)
    conformal_margin = float(np.quantile(np.abs(target_log - np.log(oof_point)), 0.90, method="higher"))
    interval_lower = oof_point * np.exp(-conformal_margin)
    interval_upper = oof_point * np.exp(conformal_margin)
    unique_dates = int(pd.to_datetime(data["listing_date"]).dt.date.nunique())
    full_support = data.groupby(["make", "model"]).size()
    row_support = np.array([full_support.get((row.make, row.model), 0) for row in data.itertuples()])
    segment_metrics = {
        f"support_at_least_{threshold}": {
            "rows": int((row_support >= threshold).sum()),
            **_extended_metrics(target[row_support >= threshold], oof_point[row_support >= threshold]),
        }
        for threshold in (5, 10)
    }
    metrics: dict[str, Any] = {
        "dataset": "real public Divar/Bama listings",
        "rows": len(data),
        "unique_listing_dates": unique_dates,
        "validation_strategy": "5-fold shuffled out-of-fold validation",
        "temporal_validation_available": unique_dates >= 30,
        "validation_warning": (
            "Only a few collection dates are available; these scores do not measure future market drift."
            if unique_dates < 30 else None
        ),
        "model": _extended_metrics(target, oof_point),
        "baseline_hierarchical_median": _extended_metrics(target, oof_baseline),
        "segments": segment_metrics,
        "interval_method": "symmetric log residual interval with out-of-fold conformal expansion",
        "interval_coverage_oof": round(float(np.mean((target >= interval_lower) & (target <= interval_upper))), 4),
        "mean_interval_width_pct_oof": round(float(np.mean((interval_upper - interval_lower) / oof_point)), 4),
        "folds": fold_metrics,
        "fallback_threshold": fallback_threshold,
    }

    features = build_features(data)
    log_target = np.log(target)
    point = _real_pipeline(random_seed=random_seed).fit(features, log_target)
    support, medians, make_medians, global_median = _summaries(data)
    return RealModelBundle(
        point_model=point,
        lower_model=None,
        upper_model=None,
        listings=data.copy(),
        metrics=metrics,
        trained_at=pd.Timestamp.utcnow().isoformat(),
        transaction_to_ask_ratio=transaction_to_ask_ratio,
        conformal_margin_log=conformal_margin,
        lower_quantile=0.05,
        upper_quantile=0.95,
        exact_support=support,
        exact_medians=medians,
        make_medians=make_medians,
        global_median=global_median,
        fallback_threshold=fallback_threshold,
    )
