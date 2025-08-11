from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from datetime import datetime, timedelta, timezone
from sqlalchemy import and_
import yaml

from apps.api.db import Decision, Event, session_scope
from apps.sidecar.roles.design import critique_ia
from apps.sidecar.roles.engineering import critique_arch
from apps.sidecar.roles.product import critique_prd
from apps.sidecar.roles.policy import check_compliance
from apps.sidecar.roles.research import note_competitive


@dataclass
class Proposal:
    title: str
    body: str
    score: float
    expected_impact: str


def _last_7d_metrics() -> Tuple[Optional[int], Optional[float], Optional[float]]:
    # Returns p95_turn_latency_ms, error_rate, avg_price_usd
    with session_scope() as s:
        seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7)
        q_turns = s.query(Event).filter(and_(Event.name == "turn", Event.ts >= seven_days_ago))
        total = q_turns.count()
        if total == 0:
            return None, None, None
        # p95 latency approx: use order by and pick index
        latencies = [int((ev.props or {}).get("total_turn_latency_ms", 0)) for ev in q_turns.all()]
        latencies.sort()
        p95 = latencies[int(0.95 * (len(latencies) - 1))]
        # error rate based on interruption or canary.rollback events (rough proxy)
        errors = (
            s.query(Event)
            .filter(and_(Event.name.in_(["interruption", "canary.rollback"]), Event.ts >= seven_days_ago))
            .count()
        )
        err_rate = errors / max(total, 1)
        prices = [float((ev.props or {}).get("price_usd", 0.0)) for ev in q_turns.all()]
        avg_price = sum(prices) / max(len(prices), 1)
        return p95, err_rate, avg_price


class OpsBrain:
    def __init__(self, config_path: Path):
        self.config_path = config_path
        with open(config_path, "r", encoding="utf-8") as f:
            self.config = yaml.safe_load(f)

    def propose(self) -> List[Proposal]:
        p95, err, avg_price = _last_7d_metrics()
        proposals: List[Proposal] = []
        if p95 is not None and p95 > 1500:
            proposals.append(
                Proposal(
                    title="Lower TTS tier",
                    body="Switch TTS provider tier to reduce synthesis time and cost",
                    score=0.6,
                    expected_impact="-10% cost, -5% tts_ms",
                )
            )
        if err is not None and err > 0.05:
            proposals.append(
                Proposal(
                    title="Reduce rollout of VOICE_AVATAR_MVP",
                    body="Decrease rollout percent to reduce error exposure",
                    score=0.7,
                    expected_impact="-err_rate",
                )
            )
        if not proposals:
            proposals.append(
                Proposal(
                    title="Switch to cheaper LLM",
                    body=f"Use lower-cost LLM for casual turns (avg price ${avg_price:.4f} per turn)",
                    score=0.55,
                    expected_impact="-20% llm_cost",
                )
            )
        return proposals

    def critique(self, proposals: List[Proposal]) -> List[Proposal]:
        annotated: List[Proposal] = []
        for p in proposals:
            rationale = "\n".join(
                [
                    critique_ia(p.body),
                    critique_arch(p.body),
                    critique_prd(p.body),
                    check_compliance(p.body),
                    note_competitive(p.body),
                ]
            )
            annotated.append(Proposal(title=p.title, body=f"{p.body}\n{rationale}", score=p.score, expected_impact=p.expected_impact))
        return sorted(annotated, key=lambda p: p.score, reverse=True)[:3]

    def vote(self, proposals: List[Proposal]) -> Proposal:
        return max(proposals, key=lambda p: p.score)

    def execute(self, proposal: Proposal) -> Dict[str, Any]:
        # Persist proposal; execution of PR is handled by a Celery task
        with session_scope() as s:
            d = Decision(title=proposal.title, body=json.dumps({
                "body": proposal.body,
                "expected_impact": proposal.expected_impact,
            }), status="open")
            s.add(d)
            s.flush()
            decision_id = int(d.id)
        return {"queued": True, "decision_id": decision_id}


def run_daily() -> Dict[str, Any]:
    brain = OpsBrain(Path("agents/projects/ai-tutor.yaml"))
    props = brain.propose()
    reviewed = brain.critique(props)
    winner = brain.vote(reviewed)
    result = brain.execute(winner)
    return {"winner": winner.title, "result": result}


