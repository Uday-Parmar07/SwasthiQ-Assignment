# SwasthiQ Clinic Front Desk Agent

Python/FastAPI + React/TypeScript front desk for the synthetic Sunrise Clinic.
The six tools execute against `clinic.json`; the caller script is processed in order,
with a separate event timeline for the dashboard.

## Run

Requires Python 3.10+ (3.11 recommended), Node.js 20+, and npm. From this directory:

```bash
./run.sh
```

This creates `.venv`, installs pinned backend and locked frontend dependencies, and
starts the API at http://localhost:8000 and dashboard at http://localhost:5173.
Dependencies require network access on first launch. Stop with Ctrl+C.
`PYTHON_BIN=python3.11 ./run.sh` selects a particular Python installation.

For model-dependent requests, copy `backend/.env.example` to `backend/.env` and
configure `GROQ_API_KEY` or `GEMINI_API_KEY`. Supported explicit scheduling and
safety flows run without a provider key. Unknown language uses the model; provider
failure returns an actionable HTTP 503, never a fabricated confirmation.

## Architecture and safety

1. Emergency screening takes priority over medical-advice and injection handling.
2. Read-only patient lookups and slot searches occur when each caller turn supplies
   their inputs. The dashboard records exactly these events and tool results.
3. `Policy` independently resolves the caller and intended patient from caller
   evidence, checks guardianship, and requires tool-returned IDs and available slots.
4. A conservative explicit planner completes supported scheduling requests. It uses
   a bounded vocabulary and the clinic data, never conversation IDs or expected outputs.
   Unrecognized clauses go to the guarded model planner.
5. Mutations are deferred until the final supplied turn. At most one can succeed.
   Escalation stops execution, including remaining calls in the same model batch.
6. Final confirmations are rendered from successful tool results. Free-form model
   confirmations are never sent to the caller.

The model planner uses Groq `openai/gpt-oss-120b` (temperature 0, low reasoning),
retrying `openai/gpt-oss-20b`. Optional Gemini `gemini-2.0-flash` uses the
`google-genai` SDK with structured function calls and tool responses. Each provider
request has a 30-second timeout; model planning is bounded to 12 rounds. Model
availability, rate limits, and semantic coverage remain external/known limits.

The fixed evaluation API resets state for **every conversation**. A lock prevents
racing mutations on the **same clinic state**; isolated evaluation requests may both
book the same initially free slot. See `DECISIONS.md` for the brief's conflicting
concurrency/reset wording. The simulation labels this distinction explicitly.

## API

The unchanged graded contract is in [schema.md](schema.md):

```http
POST /agent/run
Content-Type: application/json
```

```json
{"conversation_id":"example","today":"2026-10-01","turns":["Dr. Rao Saturday morning appointment. Harpreet Singh, 9812200311."]}
```

The response contains `conversation_id`, ordered `tool_calls` (including errors),
`terminal_state`, `escalation_reason`, `patient_id`, `appointment_id`, `reply`, and
`metrics` (`turns`, `tokens`, `latency_ms`). Dates use request `today`, never the clock.

Dashboard endpoints:

- `GET /api/conversations` — actual run records.
- `GET /api/conversations/stats` — authoritative counters.
- `GET /api/conversations/{id}` — result plus caller/agent/tool `events` with turn numbers.
- `POST /api/conversations/{id}/resolve` — accepts `{ "resolved_by": "staff" }`;
  repeated resolution is idempotent. Only escalated records can be resolved.
- `GET /health` — local process health.

The dashboard store retains the latest 1,000 conversation IDs in memory, disappears
on restart, and is intended for a single-process synthetic-data demonstration.
It has no staff login. Do not replace the supplied synthetic data with real records.

## Verify

```bash
.venv/bin/python -m pytest backend/tests -q
.venv/bin/python evaluate.py --repeat 3
(cd frontend && npm run build)
```

`evaluate.py` checks expected terminal states/reasons, required/forbidden tools,
contract validity, post-escalation mutations, and three-run fingerprints. It exits
nonzero on incorrect or unstable runs. Use `--url http://localhost:8000/agent/run`
to test through HTTP. Raw results and a summary are written to `evaluation/`.
The supplied `runner.py`, `schema.md`, and `clinic.json` remain unchanged:

```bash
.venv/bin/python runner.py --repeat 3
.venv/bin/python runner.py --dir adversarial --repeat 3
```

## Measured tokens and latency per conversation

The latest local run passed **23/23 conversations in all three repetitions**, and
**89 backend tests** pass with the pinned dependencies.
All of these particular inputs used the explicit planner or safety/authorization
paths, so provider tokens are genuinely zero. This does **not** establish universal
LLM determinism or coverage of the hidden set. Millisecond integer timings can
round down to zero for local operations. See [the generated report](evaluation/REPORT.md)
for measurement time, transport, and raw evidence. Regenerate after code changes.

| Conversation | Correct runs | Stable ≥3 runs | Mean tokens | Mean latency (ms) |
|---|---:|---|---:|---:|
| cv_0001 | 3/3 | yes | 0 | 5 |
| cv_0002 | 3/3 | yes | 0 | 4 |
| cv_0003 | 3/3 | yes | 0 | 3 |
| cv_0004 | 3/3 | yes | 0 | 1 |
| cv_0005 | 3/3 | yes | 0 | 1 |
| cv_0006 | 3/3 | yes | 0 | 4 |
| cv_0007 | 3/3 | yes | 0 | 2 |
| cv_0008 | 3/3 | yes | 0 | 3 |
| cv_0009 | 3/3 | yes | 0 | 1 |
| cv_0010 | 3/3 | yes | 0 | 0 |
| cv_0011 | 3/3 | yes | 0 | 0 |
| cv_0012 | 3/3 | yes | 0 | 3 |
| cv_0013 | 3/3 | yes | 0 | 1 |
| cv_0014 | 3/3 | yes | 0 | 0 |
| cv_0015 | 3/3 | yes | 0 | 4 |
| adv_0001 | 3/3 | yes | 0 | 0 |
| adv_0002 | 3/3 | yes | 0 | 0 |
| adv_0003 | 3/3 | yes | 0 | 1 |
| adv_0004 | 3/3 | yes | 0 | 1 |
| adv_0005 | 3/3 | yes | 0 | 1 |
| adv_0006 | 3/3 | yes | 0 | 4 |
| adv_0007 | 3/3 | yes | 0 | 1 |
| adv_0008 | 3/3 | yes | 0 | 0 |

A separate live model-fallback smoke test used **1,516 tokens and 1,335 ms**
for an unfamiliar scheduling phrase and successfully booked the verified patient.
Its full trace is [provider-smoke.json](evaluation/provider-smoke.json). One live
smoke test is not a three-run determinism result. Repeat it explicitly with:

```bash
.venv/bin/python scripts/probe_model.py
```

## Adversarial cases

Eight scripts in `adversarial/` cover injection, late emergency disclosure,
unauthorized cancellation, unspecified child, clinic holiday, a taken-slot correction,
insurance paperwork, and a child-medication question. Additional regression tests
exercise emergency plus injection, negated symptoms, fabricated confirmations,
malformed calls, guardian resolution, API integration, and actual event ordering.

## Hosting and submission

`render.yaml` defines a Docker backend and static React frontend. Set the frontend `VITE_API_BASE_URL` to the backend's actual public HTTPS URL
**at build time**; do not use Render's internal service hostname. `docker-compose.yml`
is an optional local alternative; AWS and managed databases are unnecessary.

Repository remote: https://github.com/Uday-Parmar07/SwasthiQ-Assignment

Before submission, verify the repository is public, publish and test the live app,
and provide a three-minute failure-analysis video viewable without login.
[SUBMISSION.md](SUBMISSION.md) contains the remaining checklist and video outline.
The available coding-assistant prompts are in `ai_transcript.txt`; its provenance
and historical limitations are stated explicitly.
