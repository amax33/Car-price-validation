"""Freeze real data, validate/train the final model, and save submission artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from car_market.cleaning import clean_listings
from car_market.config import settings
from car_market.model import ModelBundle
from car_market.real_training import train_real_model
from car_market.schemas import CarInput
from car_market.service import PriceService
from car_market.storage import load_listings


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=Path("data/real_market.db"))
    parser.add_argument("--release-root", type=Path, default=Path("data/releases"))
    parser.add_argument("--artifacts", type=Path, default=Path("artifacts"))
    parser.add_argument("--folds", type=int, default=5)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--no-activate", action="store_true", help="Do not replace artifacts/model.joblib")
    args = parser.parse_args()
    if not args.database.exists():
        parser.error(f"database not found: {args.database}")
    if args.folds < 3 or args.folds > 10:
        parser.error("folds must be between 3 and 10")
    return args


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def snapshot_database(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(source) as source_db, sqlite3.connect(destination) as destination_db:
        source_db.backup(destination_db)


def choose_examples(listings: pd.DataFrame, limit: int = 5) -> list[pd.Series]:
    group_sizes = listings.groupby(["make", "model"]).size().sort_values(ascending=False)
    chosen: list[pd.Series] = []
    used_makes: set[str] = set()
    for (make, model), support in group_sizes.items():
        if support < 10 or make in used_makes:
            continue
        candidates = listings[(listings["make"] == make) & (listings["model"] == model)].copy()
        median = candidates["asking_price"].median()
        row = candidates.loc[(candidates["asking_price"] - median).abs().idxmin()]
        chosen.append(row)
        used_makes.add(str(make))
        if len(chosen) == limit:
            break
    if len(chosen) < limit:
        raise RuntimeError("Not enough well-supported distinct makes for five examples")
    return chosen


def eligible_training_rows(listings: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    non_vehicle_pattern = (
        r"حواله|حوله|فرسوده|اسقاط|اوراق|سوخته|تصادفی|گذر-موقت|اقساط|پیش.پرداخت"
    )
    malformed_price = listings["asking_price"] < 1_000
    non_standard_ad = listings["url"].fillna("").str.contains(
        non_vehicle_pattern, case=False, regex=True
    )
    eligible = ~(malformed_price | non_standard_ad)
    report = {
        "input_rows": len(listings),
        "eligible_rows": int(eligible.sum()),
        "excluded_rows": int((~eligible).sum()),
        "malformed_or_partial_price_below_1000_million_irr": int(malformed_price.sum()),
        "transfer_salvage_installment_or_nonstandard_url": int(non_standard_ad.sum()),
        "overlap_between_rules": int((malformed_price & non_standard_ad).sum()),
    }
    return listings.loc[eligible].reset_index(drop=True), report


def report_markdown(
    release_name: str,
    listings: pd.DataFrame,
    training_rows: int,
    cleaning: dict,
    eligibility: dict,
    metrics: dict,
    examples: list[dict],
    dataset_hash: str,
) -> str:
    source_counts = listings.groupby("source").size().to_dict()
    group_counts = listings.groupby(["make", "model"]).size()
    lines = [
        "# Final real-data car valuation report",
        "",
        f"Release: `{release_name}`  ",
        f"Dataset SHA-256: `{dataset_hash}`",
        "",
        "## Dataset",
        "",
        f"The frozen dataset contains **{len(listings):,} cleaned public listings**: "
        + ", ".join(f"{source} {count:,}" for source, count in source_counts.items())
        + ".",
        f"It covers {listings['make'].nunique():,} makes, {len(group_counts):,} make/model groups, "
        f"and {listings['city'].nunique():,} cities. Cleaning removed "
        f"{cleaning['duplicates_removed']:,} duplicates, {cleaning['invalid_removed']:,} invalid rows, "
        f"and {cleaning['outliers_removed']:,} robust price outliers from the database export.",
        f"Training uses **{training_rows:,} eligible whole-car ads**. It excludes {eligibility['excluded_rows']:,} "
        "malformed, partial-price, transfer-right, salvage, temporary-import, or installment-focused ads using "
        "a versioned deterministic policy.",
        "",
        "## Validation",
        "",
        "Only a few listing dates are available, so honest future-market validation is not yet possible. "
        "The reported figures use five-fold shuffled out-of-fold predictions and must be interpreted as "
        "cross-sectional model checks, not temporal backtesting.",
        "",
        "| Metric | Model | Hierarchical median baseline |",
        "|---|---:|---:|",
        f"| MAE (million IRR) | {metrics['model']['mae']:,.1f} | {metrics['baseline_hierarchical_median']['mae']:,.1f} |",
        f"| RMSE (million IRR) | {metrics['model']['rmse']:,.1f} | {metrics['baseline_hierarchical_median']['rmse']:,.1f} |",
        f"| MAPE | {metrics['model']['mape']:.2%} | {metrics['baseline_hierarchical_median']['mape']:.2%} |",
        f"| Median APE | {metrics['model']['median_ape']:.2%} | {metrics['baseline_hierarchical_median']['median_ape']:.2%} |",
        f"| WMAPE | {metrics['model']['wmape']:.2%} | {metrics['baseline_hierarchical_median']['wmape']:.2%} |",
        f"| R² | {metrics['model']['r2']:.4f} | {metrics['baseline_hierarchical_median']['r2']:.4f} |",
        "",
        "For supported segments:",
        "",
        "| Segment | Rows | MAPE | Median APE | MAE |",
        "|---|---:|---:|---:|---:|",
        *[
            f"| {name.replace('_', ' ')} | {values['rows']:,} | {values['mape']:.2%} | "
            f"{values['median_ape']:.2%} | {values['mae']:,.1f} |"
            for name, values in metrics["segments"].items()
        ],
        "",
        f"The out-of-fold interval coverage is {metrics['interval_coverage_oof']:.2%}, with mean width "
        f"{metrics['mean_interval_width_pct_oof']:.2%} of the point estimate. Because the same OOF residuals "
        "calibrate and summarize the interval, independent temporal coverage may be worse.",
        "",
        "## Five real examples",
        "",
        "| Vehicle | Listed | Estimated market | Range | Position | Confidence | Exact support |",
        "|---|---:|---:|---:|---|---:|---:|",
    ]
    for item in examples:
        request = item["request"]
        response = item["response"]
        support = next(
            (text.rsplit(" ", 2)[-2] for text in response["explanation"] if text.startswith("Training support")),
            "?",
        )
        lines.append(
            f"| {request['year']} {request['make']} {request['model']}, {request['mileage_km']:,} km "
            f"| {request['listed_price']:,.1f} | {response['estimated_market_value']:,.1f} "
            f"| {response['price_range'][0]:,.1f}–{response['price_range'][1]:,.1f} "
            f"| {response['market_position']} | {response['confidence']:.2f} | {support} |"
        )
    lines += [
        "",
        "## Fallback and API behavior",
        "",
        "Make/model groups with fewer than five training rows blend the learned estimate with an exact-model, "
        "make-level, or global median. Their ranges widen and confidence falls with exact-model support. "
        "The API returns five comparable listings and states the number of exact training examples.",
        "",
        "## Limitations",
        "",
        "- Labels are asking prices, not completed transactions.",
        "- The 0.97 transaction-to-ask ratio remains an explicit scenario assumption.",
        "- Collection spans too few dates to test inflation, drift, seasonality, or future performance.",
        "- Most body-condition values are unavailable in public structured data.",
        "- Rare models depend heavily on hierarchical fallback estimates.",
        "- Bama price magnitudes are interpreted as toman despite its current JSON-LD IRR label.",
        "",
        "This is a credible challenge submission and research prototype, not a production appraisal service.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    args = arguments()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    release_name = f"real_{timestamp}"
    release_dir = args.release_root / release_name
    release_db = release_dir / "market.db"
    snapshot_database(args.database, release_db)

    exported = load_listings(release_db)
    clean, cleaning_report = clean_listings(exported)
    dataset_path = release_dir / "listings.csv"
    clean.to_csv(dataset_path, index=False)
    dataset_hash = sha256(dataset_path)
    training, eligibility_report = eligible_training_rows(clean)
    training_path = release_dir / "training_listings.csv"
    training.to_csv(training_path, index=False)

    print(f"Frozen {len(clean):,} rows in {release_dir}", flush=True)
    bundle = train_real_model(
        training,
        transaction_to_ask_ratio=settings.transaction_to_ask_ratio,
        random_seed=args.seed,
        folds=args.folds,
    )
    args.artifacts.mkdir(parents=True, exist_ok=True)
    real_model_path = args.artifacts / "real_model.joblib"
    real_metrics_path = args.artifacts / "real_metrics.json"
    bundle.save(real_model_path)
    write_json(real_metrics_path, bundle.metrics)

    active_model = settings.artifact
    active_metrics = settings.metrics
    if not args.no_activate:
        if active_model.exists() and not (args.artifacts / "synthetic_demo_model.joblib").exists():
            try:
                old = ModelBundle.load(active_model)
                sources = set(old.listings["source"].astype(str))
                if any("demo" in source for source in sources):
                    shutil.copy2(active_model, args.artifacts / "synthetic_demo_model.joblib")
            except Exception:
                pass
        bundle.save(active_model)
        write_json(active_metrics, bundle.metrics)

    service = PriceService(bundle)
    examples: list[dict] = []
    as_of = pd.to_datetime(training["listing_date"]).max().date()
    for row in choose_examples(training):
        request = CarInput(
            make=str(row["make"]), model=str(row["model"]), trim=str(row["trim"]),
            year=int(row["year"]), mileage_km=int(row["mileage_km"]),
            body_condition=str(row["body_condition"]), city=str(row["city"]),
            transmission=str(row["transmission"]), fuel_type=str(row["fuel_type"]),
            listed_price=float(row["asking_price"]), as_of_date=as_of,
        )
        response = service.estimate(request)
        examples.append({
            "source": str(row["source"]),
            "source_listing_id": str(row["source_listing_id"]),
            "source_url": str(row.get("url", "")),
            "request": request.model_dump(mode="json"),
            "response": response.model_dump(mode="json"),
        })
    examples_path = args.artifacts / "real_example_outputs.json"
    write_json(examples_path, examples)

    report = report_markdown(
        release_name, clean, len(training), cleaning_report.as_dict(), eligibility_report,
        bundle.metrics, examples, dataset_hash
    )
    report_path = Path("FINAL_REPORT.md")
    report_path.write_text(report, encoding="utf-8")
    shutil.copy2(report_path, release_dir / "FINAL_REPORT.md")

    release_metadata = {
        "release": release_name,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "dataset_rows": len(clean),
        "training_rows": len(training),
        "dataset_sha256": dataset_hash,
        "database_sha256": sha256(release_db),
        "sources": clean.groupby("source").size().to_dict(),
        "cleaning": cleaning_report.as_dict(),
        "eligibility": eligibility_report,
        "model_artifact": str(real_model_path),
        "model_sha256": sha256(real_model_path),
        "metrics": bundle.metrics,
        "examples": str(examples_path),
        "active_api_model": not args.no_activate,
    }
    write_json(release_dir / "metadata.json", release_metadata)
    write_json(args.release_root / "latest.json", {
        "release": release_name,
        "path": str(release_dir),
        "dataset_sha256": dataset_hash,
        "model_sha256": release_metadata["model_sha256"],
    })
    write_json(args.artifacts / "finalization_manifest.json", release_metadata)
    print(json.dumps({
        "release": release_name,
        "rows": len(clean),
        "training_rows": len(training),
        "model_metrics": bundle.metrics["model"],
        "baseline_metrics": bundle.metrics["baseline_hierarchical_median"],
        "report": str(report_path),
        "model": str(real_model_path),
        "examples": str(examples_path),
        "api_model_activated": not args.no_activate,
    }, indent=2))


if __name__ == "__main__":
    main()
