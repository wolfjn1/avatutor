## Autonomy Loop

- Weekly job proposes changes to improve cost and UX.
- Proposals are critiqued by lightweight role helpers and persisted to the `decisions` table with `status=open`.
- A PR skeleton is prepared on a local branch. If `GH_TOKEN` and a remote are available, the branch is pushed and a PR may be created by external automation.

### TODOs for Operators

- Configure a Git remote and `GH_TOKEN` in the runtime environment to allow pushing branches.
- Wire your PR creation bot to open PRs for branches with prefix `autonomy/`.
- Review the change plan and metrics snapshots before merging.

# Autonomy: Agentic improvement loop

This document describes how the sidecar agents propose, critique, and execute product improvements (UX, cost, reliability) while respecting guardrails and approvals.

## Pillars
- Metrics & events: comprehensive telemetry (latency, error, tokens, price)
- Experimentation: flags and experiments to gate rollouts
- Agents: propose -> critique -> vote -> execute -> observe -> iterate
- Governance: approvals, CI policy gates, rollback

## Data & metrics
- Extend `analytics/metrics.yml` to include:
  - `price_per_turn_usd`, `tokens_in`, `tokens_out`, `asr_latency_ms`, `tts_latency_ms`
- Ensure every `turn` event includes: provider names, token counts, estimated price.

## Agent workflow
1) Propose (sidecar `OpsBrain`): read past N days events/metrics; generate proposals:
   - Reduce TTS model tier by 1 to cut cost ~20%
   - Increase `VOICE_AVATAR_MVP` rollout from 5% to 25%
   - Tweak prompt template to improve answer quality
2) Critique (roles): design, engineering, product, research, policy add notes; filter risky ideas.
3) Vote: select top proposal.
4) Execute:
   - If flag/config change: open a PR changing YAML/env/flags; add `[FLAG:NAME]` in title.
   - If code change: small edits with tests; run `pytest`, `ruff`, `mypy`.
   - Request approval via `/approve` link for live flips.
5) Observe: schedule canary guardrails check; rollback if breached.

## Scheduling
- Daily: morning brief; canary stepper
- Weekly: "cost & UX tune" PR

## Human involvement points
- Provider API keys and model selections in `.env`
- Approving PRs and approval links for live flips
- Reviewing morning brief summaries

## Implementation checklist
- Providers: real STT/LLM/TTS/Avatar classes under `apps/api/providers` (toggle via env)
- Telemetry: enrich `turn` event with cost & tokens
- Sidecar: `OpsBrain.propose()` to query DB and output JSON proposal to `decisions`
- PR bot task: open PRs for flags/prompts/config; satisfy policy lints; attach metrics diff
- Scheduler: Celery Beat entries for weekly auto-PR


