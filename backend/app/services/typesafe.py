"""Access helpers for the TypeSafe (Jev) typed-judgment API configuration.

TypeSafe returns typed judgments with probabilities (Noul/Choice/Score) rather
than generated text. Workflow features that need a cheap, stable semantic check
should resolve their configuration through :func:`resolve_typesafe_config`
instead of reading the ``Setting`` row directly.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

import requests

from app.utils.redact import is_masked

DEFAULT_TYPESAFE_ENDPOINT = "https://api.typesafe.ai"


@dataclass
class TypeSafeConfig:
    endpoint: str
    api_key: str
    source: str  # "db" | "env"


class TypeSafeConfigurationError(RuntimeError):
    """Raised when TypeSafe is requested but no usable configuration exists."""


def typesafe_is_configured(setting=None) -> bool:
    """Return True when TypeSafe endpoint and API key are usable.

    When ``setting`` is missing (unit tests / callers without a DB row), keep
    Jev in the Auto chain — same unknown-config rule as Softnix/LLM helpers.
    """
    if setting is None:
        return True
    try:
        resolve_typesafe_config(setting)
    except TypeSafeConfigurationError:
        return False
    return True


def resolve_typesafe_config(setting=None) -> TypeSafeConfig:
    """Return the configured TypeSafe endpoint/key, or raise a clear error.

    Endpoint and key are always taken as a pair from one source — never an env
    key sent to a DB endpoint. A DB endpoint (admin UI) wins; only when it is
    empty are TYPESAFE_ENDPOINT / TYPESAFE_API_KEY used. A masked key echoed
    back into the DB is treated as unset.
    """
    db_endpoint = (getattr(setting, "typesafe_endpoint", None) or "").strip() if setting is not None else ""
    if db_endpoint:
        key = (getattr(setting, "typesafe_api_key", None) or "").strip()
        if not key or is_masked(key):
            raise TypeSafeConfigurationError(
                "TypeSafe Endpoint is set in Settings but its API Key is missing."
            )
        return TypeSafeConfig(endpoint=db_endpoint.rstrip("/"), api_key=key, source="db")
    endpoint = (os.environ.get("TYPESAFE_ENDPOINT") or "").strip()
    api_key = (os.environ.get("TYPESAFE_API_KEY") or "").strip()
    if not endpoint or not api_key:
        raise TypeSafeConfigurationError(
            "TypeSafe is not configured. Set the Endpoint and API Key in Settings, "
            "or provide TYPESAFE_ENDPOINT / TYPESAFE_API_KEY environment variables."
        )
    return TypeSafeConfig(endpoint=endpoint.rstrip("/"), api_key=api_key, source="env")


def typesafe_config_source(setting=None) -> str:
    """'db' | 'env' | 'none' — which configuration Jev will actually use."""
    try:
        return resolve_typesafe_config(setting).source
    except TypeSafeConfigurationError:
        return "none"


def typesafe_system_one(config: TypeSafeConfig, state: dict, questions: dict, model: str = "jev-latest", timeout: float = 30.0) -> dict:
    """One system_one call returning typed answers (raises on HTTP errors)."""
    response = requests.post(
        config.endpoint + "/v1/systemone",
        json={"model": model, "state": state, "questions": questions},
        headers={
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json",
            "accept": "application/json",
        },
        timeout=timeout,
    )
    response.raise_for_status()
    return response.json()


# ── Decision helpers (jev_score / jev_choice workflow nodes) ──────────────
# Both wrap typesafe_system_one with the SAME /v1/systemone endpoint; Score and
# Choice are question TYPES inside System One, not separate REST resources.

SCORE_SCALES: dict[str, list[str]] = {
    # scale key -> ordered anchor labels for the API `criteria` levels (low → high)
    "0_100": ["0 — ไม่พบหลักฐาน/ไม่ตรงเกณฑ์", "25 — ต่ำกว่าเกณฑ์มาก", "50 — ผ่านเกณฑ์บางส่วน",
              "75 — ตรงเกณฑ์ส่วนใหญ่", "100 — ตรงเกณฑ์สมบูรณ์"],
    "0_10": ["0 — ไม่พบหลักฐาน", "2 — ต่ำ", "4 — ปานกลางต่ำ", "6 — ปานกลาง", "8 — สูง", "10 — สูงสุด"],
    "1_5": ["1 — ต่ำสุด", "2 — ต่ำ", "3 — ปานกลาง", "4 — สูง", "5 — สูงสุด"],
}
SCORE_SCALE_MAX: dict[str, float] = {"0_100": 100.0, "0_10": 10.0, "1_5": 5.0}
SCORE_SCALE_MIN: dict[str, float] = {"0_100": 0.0, "0_10": 0.0, "1_5": 1.0}


def typesafe_score(
    config: TypeSafeConfig,
    state: dict,
    score_name: str,
    rubric: list[dict],
    scale: str = "0_100",
    timeout: float = 30.0,
    model: str = "jev-latest",
) -> dict:
    """One System One call scoring `state` against a weighted rubric.

    The API takes ordered level strings only, so the weighted UX rubric travels
    in `instructions` and the level anchors come from the UI scale. Returns the
    raw answer dict: {score (index float), confidence, probabilities?}.
    """
    levels = SCORE_SCALES.get(scale) or SCORE_SCALES["0_100"]
    questions = {
        "overall": {
            "type": "score",
            "instructions": {
                "score_name": score_name,
                "scale": scale,
                "rubric": rubric,
                "question": f"ให้คะแนน '{score_name}' ตามเกณฑ์ (rubric) ที่ให้ โดยอ้างเฉพาะข้อมูลใน state",
            },
            "criteria": levels,
        }
    }
    response = typesafe_system_one(config, state, questions, model=model, timeout=timeout)
    answer = (response.get("answers") or {}).get("overall") or {}
    return {
        "index": answer.get("score"),
        "confidence": answer.get("confidence"),
        "probabilities": answer.get("probabilities") or {},
        "model": response.get("model", model),
    }


def typesafe_choice(
    config: TypeSafeConfig,
    state: dict,
    choice_name: str,
    options: list[dict],
    timeout: float = 30.0,
    model: str = "jev-latest",
) -> dict:
    """One System One call choosing among `options` [{key,label,description?}].

    Mirrors the Choice shape already proven by `field_mapping.jev_mapping`,
    plus the vendor `probabilities` map when the provider returns it.
    """
    criteria: dict[str, object] = {}
    for option in options:
        criteria[str(option.get("key"))] = (
            str(option.get("description") or option.get("label") or option.get("key")) or None
        )
    questions = {
        "route": {
            "type": "choice",
            "instructions": {
                "choice_name": choice_name,
                "options": [{"key": o.get("key"), "label": o.get("label")} for o in options],
                "question": f"เลือกหนึ่งตัวเลือกสำหรับ '{choice_name}' โดยอ้างเฉพาะข้อมูลใน state",
            },
            "criteria": criteria,
        }
    }
    response = typesafe_system_one(config, state, questions, model=model, timeout=timeout)
    answer = (response.get("answers") or {}).get("route") or {}
    return {
        "choice": answer.get("choice"),
        "confidence": answer.get("confidence"),
        "probabilities": answer.get("probabilities") or {},
        "model": response.get("model", model),
    }


def typesafe_noul(
    config: TypeSafeConfig,
    state: dict,
    question: str,
    timeout: float = 30.0,
    model: str = "jev-latest",
) -> dict:
    """One System One call answering a single yes/no `noul` question.

    Vendor answer is exactly {type:"noul", noul: 0..1} — no confidence, no
    evidence. Returns {noul, model} only; callers must not fabricate the rest.
    """
    questions = {
        "noul": {
            "type": "noul",
            "instructions": question,
        }
    }
    response = typesafe_system_one(config, state, questions, model=model, timeout=timeout)
    answer = (response.get("answers") or {}).get("noul") or {}
    return {
        "noul": answer.get("noul"),
        "model": response.get("model", model),
    }
