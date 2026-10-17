from dataclasses import replace

from car_market.config import settings
from car_market.demo_data import generate_demo_data
from car_market.model import ModelBundle
from car_market.pipeline import prepare_data, train
from car_market.schemas import CarInput
from car_market.service import PriceService


def test_end_to_end_pipeline(tmp_path):
    config = replace(
        settings,
        raw_data=tmp_path / "raw.csv",
        clean_data=tmp_path / "clean.csv",
        database=tmp_path / "market.db",
        artifact=tmp_path / "model.joblib",
        metrics=tmp_path / "metrics.json",
    )
    generate_demo_data(config.raw_data, rows=180, seed=3)
    clean, report = prepare_data(config)
    assert report["output_rows"] == len(clean)
    assert config.database.exists()
    bundle = train(config)
    reloaded = ModelBundle.load(config.artifact)
    result = PriceService(reloaded).estimate(CarInput(
        make="سایپا", model="کوییک", trim="R", year=2022, mileage_km=35_000,
        body_condition="بدون رنگ", city="Tehran", listed_price=6_500,
    ))
    assert bundle.metrics["validation_rows"] > 0
    assert result.price_range[0] <= result.estimated_asking_price <= result.price_range[1] / config.transaction_to_ask_ratio
    assert result.market_position in {"Below Market", "Fair", "Above Market"}
    assert len(result.comparable_vehicles) == 5

