from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from .config import settings
from .demo_data import generate_demo_data
from .model import ModelBundle
from .pipeline import prepare_data, train
from .schemas import CarInput
from .scrapers import JsonLdVehicleScraper
from .service import PriceService


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="car-market")
    commands = parser.add_subparsers(dest="command", required=True)
    demo = commands.add_parser("demo-data", help="Create labeled synthetic data for an offline demo")
    demo.add_argument("--rows", type=int, default=900)
    commands.add_parser("prepare", help="Clean raw CSV and populate SQLite")
    commands.add_parser("train", help="Train, validate, and save the models")
    scrape = commands.add_parser("scrape", help="Collect schema.org data from supplied public URLs")
    scrape.add_argument("urls", nargs="+")
    scrape.add_argument("--source", required=True)
    scrape.add_argument("--output", type=Path, default=settings.raw_data)
    scrape.add_argument("--delay", type=float, default=1.0)
    scrape.add_argument("--price-unit", choices=["million_irr", "irr", "toman"], default="million_irr")
    estimate = commands.add_parser("estimate", help="Estimate one car from a JSON file")
    estimate.add_argument("input", type=Path)
    return parser


def main() -> None:
    args = _parser().parse_args()
    if args.command == "demo-data":
        frame = generate_demo_data(settings.raw_data, args.rows, settings.random_seed)
        print(json.dumps({"rows": len(frame), "path": str(settings.raw_data), "synthetic": True}, indent=2))
    elif args.command == "prepare":
        _, report = prepare_data(settings)
        print(json.dumps(report, indent=2))
    elif args.command == "train":
        bundle = train(settings)
        print(json.dumps(bundle.metrics, indent=2))
    elif args.command == "scrape":
        result = JsonLdVehicleScraper(args.urls, args.source, args.delay, args.price_unit).collect()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(result.rows).to_csv(args.output, index=False)
        print(json.dumps({"rows": len(result.rows), "errors": result.errors, "path": str(args.output)}, indent=2))
    elif args.command == "estimate":
        payload = CarInput.model_validate_json(args.input.read_text(encoding="utf-8"))
        service = PriceService(ModelBundle.load(settings.artifact))
        print(service.estimate(payload).model_dump_json(indent=2))


if __name__ == "__main__":
    main()
