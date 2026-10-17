from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class CarInput(BaseModel):
    make: str = Field(min_length=1, examples=["Iran Khodro"])
    model: str = Field(min_length=1, examples=["Dena Plus"])
    trim: str = Field(default="base", examples=["Turbo Automatic"])
    year: int = Field(ge=1980, le=2100)
    mileage_km: int = Field(ge=0, le=2_000_000)
    body_condition: str = Field(default="clean")
    city: str = Field(default="Tehran")
    transmission: str = Field(default="manual")
    fuel_type: str = Field(default="gasoline")
    listed_price: float | None = Field(default=None, gt=0, description="Price in million IRR")
    as_of_date: date = Field(default_factory=date.today)

    @field_validator("make", "model", "trim", "body_condition", "city", "transmission", "fuel_type")
    @classmethod
    def strip_text(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("must not be blank")
        return value


class ComparableVehicle(BaseModel):
    source: str
    source_listing_id: str
    make: str
    model: str
    trim: str
    year: int
    mileage_km: int
    city: str
    asking_price: float
    listing_date: date
    similarity: float = Field(ge=0, le=1)


class PriceEstimate(BaseModel):
    currency_unit: Literal["million IRR"] = "million IRR"
    estimated_asking_price: float
    estimated_market_value: float
    price_range: tuple[float, float]
    listed_price: float | None
    difference_percent: float | None
    market_position: Literal["Below Market", "Fair", "Above Market", "Not Assessed"]
    confidence: float = Field(ge=0, le=1)
    confidence_label: Literal["low", "medium", "high"]
    comparable_vehicles: list[ComparableVehicle]
    explanation: list[str]
    caveat: str

