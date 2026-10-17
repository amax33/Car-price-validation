from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OrdinalEncoder


CATEGORICAL = [
    "make", "model", "trim", "body_condition", "city", "transmission", "fuel_type",
]
NUMERIC = ["year", "mileage_km", "vehicle_age", "mileage_per_year", "market_month"]
FEATURES = CATEGORICAL + NUMERIC


def build_features(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    dates = pd.to_datetime(result.get("as_of_date", result.get("listing_date")), errors="coerce")
    if dates.isna().any():
        raise ValueError("All rows need a valid listing_date or as_of_date")
    result["vehicle_age"] = (dates.dt.year - result["year"]).clip(lower=0)
    result["mileage_per_year"] = result["mileage_km"] / result["vehicle_age"].clip(lower=1)
    result["market_month"] = dates.dt.year * 12 + dates.dt.month
    return result[FEATURES]


def _pipeline(loss: str, quantile: float | None = None, random_seed: int = 42) -> Pipeline:
    category_pipeline = Pipeline([
        ("imputer", SimpleImputer(strategy="most_frequent")),
        ("encoder", OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1)),
    ])
    numeric_pipeline = Pipeline([("imputer", SimpleImputer(strategy="median"))])
    processor = ColumnTransformer([
        ("categorical", category_pipeline, CATEGORICAL),
        ("numeric", numeric_pipeline, NUMERIC),
    ])
    kwargs: dict[str, Any] = {"loss": loss, "random_state": random_seed, "max_iter": 250, "l2_regularization": 1.0}
    if quantile is not None:
        kwargs["quantile"] = quantile
    return Pipeline([("features", processor), ("model", HistGradientBoostingRegressor(**kwargs))])


@dataclass
class ModelBundle:
    point_model: Pipeline
    lower_model: Pipeline
    upper_model: Pipeline
    listings: pd.DataFrame
    metrics: dict[str, Any]
    trained_at: str
    transaction_to_ask_ratio: float
    conformal_margin_log: float = 0.0
    lower_quantile: float = 0.15
    upper_quantile: float = 0.85

    def predict(self, frame: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        features = build_features(frame)
        point = np.exp(self.point_model.predict(features))
        lower_raw = np.exp(self.lower_model.predict(features) - self.conformal_margin_log)
        upper_raw = np.exp(self.upper_model.predict(features) + self.conformal_margin_log)
        lower = np.minimum.reduce([lower_raw, point, upper_raw])
        upper = np.maximum.reduce([lower_raw, point, upper_raw])
        return point, lower, upper

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(self, path)

    @classmethod
    def load(cls, path: str | Path) -> "ModelBundle":
        return joblib.load(path)


def _time_split(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, str]:
    ordered = frame.sort_values("listing_date").reset_index(drop=True)
    train_cut = max(int(len(ordered) * 0.70), 1)
    calibration_cut = max(int(len(ordered) * 0.85), train_cut + 1)
    cutoff = str(ordered.iloc[calibration_cut]["listing_date"])
    return (
        ordered.iloc[:train_cut].copy(),
        ordered.iloc[train_cut:calibration_cut].copy(),
        ordered.iloc[calibration_cut:].copy(),
        cutoff,
    )


def _baseline(train: pd.DataFrame, validation: pd.DataFrame) -> np.ndarray:
    group_median = train.groupby(["make", "model"])["asking_price"].median()
    global_median = float(train["asking_price"].median())
    return np.array([
        group_median.get((row.make, row.model), global_median)
        for row in validation.itertuples()
    ])


def _regression_metrics(y: np.ndarray, predicted: np.ndarray) -> dict[str, float]:
    denominator = np.maximum(np.abs(y), 1.0)
    return {
        "mae": round(float(mean_absolute_error(y, predicted)), 3),
        "rmse": round(float(np.sqrt(mean_squared_error(y, predicted))), 3),
        "mape": round(float(np.mean(np.abs(y - predicted) / denominator)), 4),
        "r2": round(float(r2_score(y, predicted)), 4),
    }


def train_model(
    listings: pd.DataFrame,
    transaction_to_ask_ratio: float = 0.97,
    random_seed: int = 42,
) -> ModelBundle:
    if len(listings) < 50:
        raise ValueError("At least 50 clean listings are required")
    train, calibration, validation, cutoff = _time_split(listings)
    x_train, x_validation = build_features(train), build_features(validation)
    y_train = np.log(train["asking_price"].to_numpy())
    y_validation = validation["asking_price"].to_numpy()

    point = _pipeline("absolute_error", random_seed=random_seed).fit(x_train, y_train)
    lower = _pipeline("quantile", 0.15, random_seed).fit(x_train, y_train)
    upper = _pipeline("quantile", 0.85, random_seed).fit(x_train, y_train)
    calibration_features = build_features(calibration)
    calibration_target = np.log(calibration["asking_price"].to_numpy())
    calibration_lower = lower.predict(calibration_features)
    calibration_upper = upper.predict(calibration_features)
    nonconformity = np.maximum.reduce([
        calibration_lower - calibration_target,
        calibration_target - calibration_upper,
        np.zeros(len(calibration)),
    ])
    # Split-conformal correction for a conservative nominal 90% market range.
    level = min(1.0, np.ceil((len(nonconformity) + 1) * 0.90) / len(nonconformity))
    conformal_margin = float(np.quantile(nonconformity, level, method="higher"))
    predicted = np.exp(point.predict(x_validation))
    lower_pred = np.exp(lower.predict(x_validation) - conformal_margin)
    upper_pred = np.exp(upper.predict(x_validation) + conformal_margin)
    baseline = _baseline(train, validation)
    metrics: dict[str, Any] = {
        "validation_strategy": "70% train / 15% interval calibration / 15% final test, ordered by listing_date",
        "cutoff_date": cutoff,
        "train_rows": len(train),
        "calibration_rows": len(calibration),
        "validation_rows": len(validation),
        "model": _regression_metrics(y_validation, predicted),
        "baseline_make_model_median": _regression_metrics(y_validation, baseline),
        "interval_target_coverage": 0.9,
        "interval_coverage": round(float(np.mean((y_validation >= lower_pred) & (y_validation <= upper_pred))), 4),
        "mean_interval_width_pct": round(float(np.mean((upper_pred - lower_pred) / predicted)), 4),
    }

    # Refit on all observations only after honest holdout metrics have been captured.
    all_features = build_features(listings)
    all_target = np.log(listings["asking_price"].to_numpy())
    point.fit(all_features, all_target)
    lower.fit(all_features, all_target)
    upper.fit(all_features, all_target)
    return ModelBundle(
        point_model=point,
        lower_model=lower,
        upper_model=upper,
        listings=listings.copy(),
        metrics=metrics,
        trained_at=pd.Timestamp.utcnow().isoformat(),
        transaction_to_ask_ratio=transaction_to_ask_ratio,
        conformal_margin_log=conformal_margin,
    )
