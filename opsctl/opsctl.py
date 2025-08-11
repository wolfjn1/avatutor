from __future__ import annotations

from typing import Optional

import typer

from apps.api.db import session_scope, FeatureFlag, DLQ


app = typer.Typer(help="Ops CLI for flags, approvals, jobs, and DLQ")
approve_app = typer.Typer(help="Approvals")
app.add_typer(approve_app, name="approve")
approve_app = typer.Typer(help="Approvals")
app.add_typer(approve_app, name="approve")


@app.command("flags")
def flags_cmd(action: str = typer.Argument("list"), name: Optional[str] = None, on: bool = False, percent: Optional[int] = None) -> None:
    if action == "list":
        with session_scope() as s:
            rows = s.query(FeatureFlag).all()
            for r in rows:
                typer.echo(f"{r.name}: enabled={r.enabled} percent={r.rollout_percent}")
        return
    if action == "set":
        if not name:
            raise typer.BadParameter("name required")
        with session_scope() as s:
            flag = s.merge(FeatureFlag(name=name))
            flag.enabled = on or flag.enabled
            if percent is not None:
                flag.rollout_percent = percent
            s.flush()
        typer.echo("ok")
        return
    raise typer.BadParameter("unknown action")


@app.command("dlq")
def dlq_cmd(action: str = typer.Argument("list"), id: Optional[int] = None) -> None:  # noqa: A002
    if action == "list":
        with session_scope() as s:
            rows = s.query(DLQ).all()
            for r in rows:
                typer.echo(f"{r.id} attempts={r.attempts} error={r.error[:40]}")
        return
    if action == "replay":
        if id is None:
            raise typer.BadParameter("id required")
        with session_scope() as s:
            item = s.get(DLQ, id)
            if item:
                s.delete(item)
        typer.echo("requeued")
        return
    raise typer.BadParameter("unknown action")


@app.command("jobs")
def jobs_cmd(action: str, name: Optional[str] = None) -> None:
    if action == "run" and name == "morning-brief":
        from apps.api.tasks.reports import generate_morning_brief

        path = generate_morning_brief()  # type: ignore[call-arg]
        typer.echo(path)
        return
    if action == "run" and name == "canary-check":
        from apps.api.tasks.guardrails import canary_check

        typer.echo("running canary check...")
        ok = canary_check()  # type: ignore[call-arg]
        typer.echo(f"canary ok={ok}")
        return
    typer.echo("noop")


@app.command("workers")
def workers_scale(queue: str = "api", replicas: int = 1) -> None:
    typer.echo(f"Would scale queue={queue} to replicas={replicas} in cloud env. No-op locally.")


@approve_app.command("mint")
def approve_mint(decision_key: str, action: str = "flip_flag", flag: Optional[str] = None, percent: int = 100) -> None:
    """Mint an approval token and print the approval link."""
    from apps.api.security import mint_approval_token

    payload = {"decision_key": decision_key, "action": action}
    if flag:
        payload.update({"flag": flag, "percent": percent})
    token = mint_approval_token(payload)
    typer.echo(f"http://localhost:8080/approve?token={token}")


if __name__ == "__main__":
    app()


