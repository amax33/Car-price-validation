from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .normalization import (
    normalize_body,
    normalize_make,
    normalize_model,
    normalize_named,
    normalize_text,
    normalize_year,
    parse_number,
)


REQUIRED = {
    "source", "source_listing_id", "make", "model", "year", "mileage_km",
    "body_condition", "city", "asking_price", "listing_date",
}


@dataclass
class CleaningReport:
    input_rows: int = 0
    output_rows: int = 0
    duplicates_removed: int = 0
    invalid_removed: int = 0
    outliers_removed: int = 0
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return self.__dict__


def _remove_group_outliers(frame: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Remove extreme prices using robust within-model median absolute deviation."""
    keep = pd.Series(True, index=frame.index)
    for _, group in frame.groupby(["make", "model"], dropna=False):
        if len(group) < 8:
            continue
        log_price = np.log(group["asking_price"])
        median = log_price.median()
        mad = np.median(np.abs(log_price - median))
        if mad > 0:
            robust_z = 0.6745 * np.abs(log_price - median) / mad
            keep.loc[group.index] = robust_z <= 5.0
    removed = int((~keep).sum())
    return frame.loc[keep].copy(), removed


def clean_listings(raw: pd.DataFrame) -> tuple[pd.DataFrame, CleaningReport]:
    missing = REQUIRED - set(raw.columns)
    if missing:
        raise ValueError(f"Missing required columns: {', '.join(sorted(missing))}")

    df = raw.copy()
    report = CleaningReport(input_rows=len(df))
    for optional, default in {
        "trim": "base", "transmission": "manual", "fuel_type": "gasoline", "url": "",
    }.items():
        if optional not in df:
            df[optional] = default

    df["source"] = df["source"].map(normalize_text).str.casefold()
    df["source_listing_id"] = df["source_listing_id"].map(normalize_text)
    df["make"] = df["make"].map(normalize_make)
    df["model"] = df["model"].map(normalize_model)
    df["trim"] = df["trim"].map(lambda x: normalize_named(x, {}, "base"))
    df["body_condition"] = df["body_condition"].map(normalize_body)
    df["city"] = df["city"].map(lambda x: normalize_named(x, {}))
    df["transmission"] = df["transmission"].map(lambda x: normalize_named(x, {})).str.casefold()
    df["fuel_type"] = df["fuel_type"].map(lambda x: normalize_named(x, {})).str.casefold()
    df["year"] = df["year"].map(normalize_year)
    df["mileage_km"] = df["mileage_km"].map(parse_number)
    df["asking_price"] = df["asking_price"].map(parse_number)
    df["listing_date"] = pd.to_datetime(df["listing_date"], errors="coerce").dt.date

    before = len(df)
    df = df.drop_duplicates(subset=["source", "source_listing_id"], keep="last")
    fingerprint = ["make", "model", "trim", "year", "mileage_km", "city", "asking_price", "listing_date"]
    df = df.drop_duplicates(subset=fingerprint, keep="first")
    report.duplicates_removed = before - len(df)

    valid = (
        df["year"].between(1980, 2100)
        & df["mileage_km"].between(0, 2_000_000)
        & df["asking_price"].between(10, 1_000_000)
        & df["listing_date"].notna()
        & ~df["make"].eq("unknown")
        & ~df["model"].eq("unknown")
    )
    report.invalid_removed = int((~valid).sum())
    df = df.loc[valid].copy()
    df, report.outliers_removed = _remove_group_outliers(df)
    df["year"] = df["year"].astype(int)
    df["mileage_km"] = df["mileage_km"].round().astype(int)
    df["asking_price"] = df["asking_price"].round(2)
    df = df.sort_values(["listing_date", "source", "source_listing_id"]).reset_index(drop=True)
    report.output_rows = len(df)
    if len(df) < 100:
        report.warnings.append("Small dataset: model estimates will be unstable.")
    return df, report
