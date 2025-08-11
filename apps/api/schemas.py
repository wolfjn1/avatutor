from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class FlagCreate(BaseModel):
    name: str
    description: str | None = None
    enabled: bool = False
    rollout_percent: int = Field(0, ge=0, le=100)
    created_by: str = "system"


class FlagUpdate(BaseModel):
    enabled: Optional[bool] = None
    rollout_percent: Optional[int] = Field(None, ge=0, le=100)


class FlagOut(BaseModel):
    id: int
    name: str
    description: str | None
    enabled: bool
    rollout_percent: int
    created_by: str
    created_at: datetime


class TelemetryEventIn(BaseModel):
    name: str
    session_id: str
    user_id: Optional[str] = None
    props: Dict[str, Any] = Field(default_factory=dict)


class TelemetryEventOut(BaseModel):
    id: int
    name: str
    session_id: str
    user_id: Optional[str]
    ts: datetime
    props: Dict[str, Any]


class ApprovalMintRequest(BaseModel):
    decision_key: str
    issued_to: str
    action: str
    flag: Optional[str] = None
    percent: Optional[int] = None


