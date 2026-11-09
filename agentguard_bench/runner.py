"""Load synthetic scenarios and run decision-only baselines."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable

from .policy import allowlist_policy

DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "scenarios.json"


def load_cases(path: Path = DATA_PATH) -> list[dict[str, Any]]:
    cases = json.loads(path.read_text(encoding="utf-8"))
    if not cases or any("expected" not in c or "id" not in c for c in cases):
        raise ValueError("scenario file must contain cases with id and expected")
    return cases


def run_policy(cases: list[dict[str, Any]], policy: Callable[[dict[str, Any]], str]) -> list[dict[str, Any]]:
    results = []
    for case in cases:
        start = time.perf_counter()
        prediction = policy(case)
        elapsed = (time.perf_counter() - start) * 1000
        results.append({
            "id": case["id"], "expected": case["expected"],
            "prediction": prediction, "latency_ms": elapsed,
        })
    return results


def run_ollama(cases: list[dict[str, Any]], model: str | None = None) -> list[dict[str, Any]]:
    from .ollama import decide
    return run_policy(cases, lambda case: decide(case, model=model))


def save_results(path: Path, name: str, rows: list[dict[str, Any]], metrics: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"policy": name, "metrics": metrics, "results": rows}, indent=2) + "\n", encoding="utf-8")
