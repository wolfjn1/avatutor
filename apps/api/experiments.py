from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

from .feature_flags import flags


EXPERIMENTS_DIR = Path(os.getenv("EXPERIMENTS_DIR", "docs/experiments")).resolve()


@dataclass
class Experiment:
    name: str
    hypothesis: str
    metrics: Dict[str, Any]
    unit: str
    sample_size: int
    guardrails: Dict[str, Any]
    SRM_check: bool


def load_experiment(name: str) -> Optional[Experiment]:
    path = EXPERIMENTS_DIR / f"{name}.yml"
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        doc = yaml.safe_load(f)
    return Experiment(
        name=doc["name"],
        hypothesis=doc["hypothesis"],
        metrics=doc.get("metrics", {}),
        unit=doc.get("unit", "session"),
        sample_size=int(doc.get("sample_size", 0)),
        guardrails=doc.get("guardrails", {}),
        SRM_check=bool(doc.get("SRM_check", True)),
    )


def assign_variant(flag_name: str, user_id: Optional[str]) -> str:
    # Simple flag-based assignment: if flag enabled for user -> treatment else control
    return "treatment" if flags.is_enabled(flag_name, user_id=user_id) else "control"


