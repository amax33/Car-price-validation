from __future__ import annotations

import re
import unicodedata
from typing import Any

import numpy as np


PERSIAN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
ARABIC_CHARS = str.maketrans({"ي": "ی", "ك": "ک", "ة": "ه", "ۀ": "ه"})

MAKE_ALIASES = {
    "ایران خودرو": "Iran Khodro",
    "iran-khodro": "Iran Khodro",
    "iran khodro": "Iran Khodro",
    "ikco": "Iran Khodro",
    "سایپا": "Saipa",
    "saipa": "Saipa",
    "پژو": "Peugeot",
    "peugeot": "Peugeot",
    "رنو": "Renault",
    "renault": "Renault",
    "هیوندای": "Hyundai",
    "hyundai": "Hyundai",
    "کیا": "Kia",
    "kia": "Kia",
}

MODEL_ALIASES = {
    "دنا پلاس": "Dena Plus",
    "dena+": "Dena Plus",
    "dena plus": "Dena Plus",
    "پژو 206": "206",
    "peugeot 206": "206",
    "206": "206",
    "پژو پارس": "Pars",
    "peugeot pars": "Pars",
    "pars": "Pars",
    "پراید 131": "Pride 131",
    "pride 131": "Pride 131",
    "کوییک": "Quick",
    "quick": "Quick",
    "تندر 90": "L90",
    "ال 90": "L90",
    "l90": "L90",
    "سانتافه": "Santa Fe",
    "santa fe": "Santa Fe",
    "سراتو": "Cerato",
    "cerato": "Cerato",
}

BODY_ALIASES = {
    "بدون رنگ": "clean",
    "سالم و بی خط و خش": "clean",
    "clean": "clean",
    "یک لکه رنگ": "one_panel",
    "یک تکه رنگ": "one_panel",
    "one panel": "one_panel",
    "چند لکه رنگ": "multiple_panels",
    "دور رنگ": "multiple_panels",
    "multiple panels": "multiple_panels",
    "تعویض": "replaced_panel",
    "replaced panel": "replaced_panel",
    "تصادفی": "damaged",
}


def normalize_text(value: Any) -> str:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return ""
    text = unicodedata.normalize("NFKC", str(value)).translate(PERSIAN_DIGITS).translate(ARABIC_CHARS)
    text = re.sub(r"[_/]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def normalize_named(value: Any, aliases: dict[str, str], default: str = "unknown") -> str:
    text = normalize_text(value)
    if not text:
        return default
    return aliases.get(text.casefold(), aliases.get(text, text.title()))


def parse_number(value: Any) -> float:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    text = normalize_text(value).replace(",", "")
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    return float(match.group()) if match else float("nan")


def normalize_year(value: Any) -> int | None:
    year = parse_number(value)
    if np.isnan(year):
        return None
    year = int(year)
    if 1300 <= year <= 1500:  # Approximate Solar Hijri conversion, sufficient for model-year bins.
        year += 621
    return year


def normalize_make(value: Any) -> str:
    return normalize_named(value, MAKE_ALIASES)


def normalize_model(value: Any) -> str:
    return normalize_named(value, MODEL_ALIASES)


def normalize_body(value: Any) -> str:
    return normalize_named(value, BODY_ALIASES)
