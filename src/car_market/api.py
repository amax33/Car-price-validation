from __future__ import annotations

from functools import lru_cache

from fastapi import FastAPI, HTTPException

from .config import settings
from .model import ModelBundle
from .schemas import CarInput, PriceEstimate
from .service import PriceService


app = FastAPI(
    title="Narin Car Market API",
    version="0.1.0",
    description="Estimates current asking price and assumption-adjusted fair market value.",
)


@lru_cache(maxsize=1)
def get_service() -> PriceService:
    if not settings.artifact.exists():
        raise FileNotFoundError("Model artifact is missing. Run `car-market train`.")
    return PriceService(ModelBundle.load(settings.artifact))


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "model": "ready" if settings.artifact.exists() else "missing"}


@app.post("/v1/estimate", response_model=PriceEstimate)
def estimate(payload: CarInput) -> PriceEstimate:
    try:
        return get_service().estimate(payload)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

