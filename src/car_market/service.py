from __future__ import annotations

import math

import numpy as np
import pandas as pd

from .model import ModelBundle
from .normalization import normalize_body, normalize_make, normalize_model, normalize_named
from .schemas import CarInput, ComparableVehicle, PriceEstimate


class PriceService:
    def __init__(self, bundle: ModelBundle):
        self.bundle = bundle

    def estimate(self, request: CarInput) -> PriceEstimate:
        row = self._normalized_row(request)
        frame = pd.DataFrame([row])
        asking_estimate, ask_lower, ask_upper = (values[0] for values in self.bundle.predict(frame))
        ratio = self.bundle.transaction_to_ask_ratio
        fair_value = asking_estimate * ratio
        lower, upper = ask_lower * ratio, ask_upper * ratio
        comparables = self._comparables(row)
        support = self._support_count(row)
        confidence = self._confidence(asking_estimate, lower, upper, comparables, support)
        listed = request.listed_price
        if listed is None:
            position, difference = "Not Assessed", None
        else:
            difference = 100 * (listed - fair_value) / fair_value
            position = "Below Market" if listed < lower else "Above Market" if listed > upper else "Fair"
        return PriceEstimate(
            estimated_asking_price=round(float(asking_estimate), 1),
            estimated_market_value=round(float(fair_value), 1),
            price_range=(round(float(lower), 1), round(float(upper), 1)),
            listed_price=listed,
            difference_percent=round(float(difference), 1) if difference is not None else None,
            market_position=position,
            confidence=round(confidence, 2),
            confidence_label="high" if confidence >= 0.75 else "medium" if confidence >= 0.5 else "low",
            comparable_vehicles=comparables,
            explanation=self._explanation(row, fair_value, comparables, support),
            caveat=(
                f"Trained on asking prices. Market value applies an assumed transaction/ask ratio of {ratio:.2f}; "
                "no completed-sale data was available, so it is not a verified transaction price."
            ),
        )

    @staticmethod
    def _normalized_row(request: CarInput) -> dict:
        row = request.model_dump()
        row["make"] = normalize_make(row["make"])
        row["model"] = normalize_model(row["model"])
        row["trim"] = normalize_named(row["trim"], {}, "base")
        row["body_condition"] = normalize_body(row["body_condition"])
        row["city"] = normalize_named(row["city"], {})
        row["transmission"] = normalize_named(row["transmission"], {}).casefold()
        row["fuel_type"] = normalize_named(row["fuel_type"], {}).casefold()
        return row

    def _comparables(self, row: dict, limit: int = 5) -> list[ComparableVehicle]:
        listings = self.bundle.listings.copy()
        dates = pd.to_datetime(listings["listing_date"])
        same_model = (listings["make"] == row["make"]) & (listings["model"] == row["model"])
        candidates = listings.loc[same_model].copy()
        if len(candidates) < limit:
            candidates = listings.loc[listings["make"] == row["make"]].copy()
        if candidates.empty:
            candidates = listings.copy()
        candidate_dates = dates.loc[candidates.index]
        year_penalty = np.abs(candidates["year"] - row["year"]) / 5
        mileage_penalty = np.abs(candidates["mileage_km"] - row["mileage_km"]) / 100_000
        age_days = np.maximum((pd.Timestamp(row["as_of_date"]) - candidate_dates).dt.days, 0)
        recency_penalty = age_days / 730
        category_penalty = (
            (candidates["model"] != row["model"]).astype(float) * 2
            + (candidates["trim"] != row["trim"]).astype(float) * 0.3
            + (candidates["city"] != row["city"]).astype(float) * 0.15
            + (candidates["body_condition"] != row["body_condition"]).astype(float) * 0.25
        )
        candidates["similarity"] = np.exp(-(year_penalty + mileage_penalty + recency_penalty + category_penalty))
        candidates = candidates.nlargest(limit, "similarity")
        return [
            ComparableVehicle(
                source=str(item.source), source_listing_id=str(item.source_listing_id),
                make=item.make, model=item.model, trim=item.trim, year=int(item.year),
                mileage_km=int(item.mileage_km), city=item.city, asking_price=float(item.asking_price),
                listing_date=pd.Timestamp(item.listing_date).date(), similarity=round(float(item.similarity), 3),
            )
            for item in candidates.itertuples()
        ]

    def _support_count(self, row: dict) -> int:
        if hasattr(self.bundle, "support_count"):
            return int(self.bundle.support_count(row))
        listings = self.bundle.listings
        return int(((listings["make"] == row["make"]) & (listings["model"] == row["model"])).sum())

    @staticmethod
    def _confidence(
        point: float,
        lower: float,
        upper: float,
        comparables: list[ComparableVehicle],
        exact_support: int,
    ) -> float:
        interval_score = math.exp(-max(upper - lower, 0) / max(point, 1))
        support_score = min(exact_support / 10, 1.0)
        similarity_score = float(np.mean([c.similarity for c in comparables])) if comparables else 0.0
        return float(np.clip(0.45 * interval_score + 0.25 * support_score + 0.30 * similarity_score, 0, 1))

    @staticmethod
    def _explanation(
        row: dict,
        fair_value: float,
        comparables: list[ComparableVehicle],
        exact_support: int,
    ) -> list[str]:
        messages = [
            f"Estimate reflects {row['year']} {row['make']} {row['model']} with {row['mileage_km']:,} km.",
            f"Body condition '{row['body_condition']}' and the {row['city']} market are model inputs.",
            f"Training support for this exact make/model is {exact_support} listings.",
        ]
        if comparables:
            median = float(np.median([item.asking_price for item in comparables]))
            messages.append(
                f"{len(comparables)} nearest listings have a median ask of {median:,.1f} million IRR; "
                f"the adjusted estimate is {fair_value:,.1f}."
            )
        return messages
