# Decisions and ambiguities

## Authority belongs to Python

The model may propose tools, but cannot establish caller identity, grant itself
access, invent a destination, select a different patient, or confirm an unexecuted
write. Both the explicit planner and model planner pass through the same policy
and six deterministic tools. Results, rather than model prose, generate final replies.
Successful mutation results determine the terminal state; a failed attempt does not.

For explicit English/transliterated-Hindi scheduling, deterministic preparation
and completion reduce cost and eliminate unnecessary confirmation loops. This
planner uses clinic data and a bounded grammar, never fixture IDs or expected
outputs. An unfamiliar clause prevents this path, so finding a recognizable date
and phone number does not silently discard an unfamiliar clinical disclosure.
The model handles unsupported language under the same policy. The supplied 23
scripts use the explicit path; their passing results are not a claim about all
unseen scripts or model behavior.

## Clinical priority and stopping

Emergency > medical advice > injection refusal. A caller who combines an emergency
with an instruction override still needs clinical escalation. A successful
escalation stops all subsequent tools. If a model emits an escalation and mutation
in one batch, escalation executes first and the mutation never executes; logs
reflect actual execution order. The clinical pre-screen examines the entire fixed
script before any mutation. Recognized emergencies need no provider key.

Explicit local negation ("no chest pain") is distinguished from an asserted symptom;
"cannot breathe" is not treated as negation. Coverage includes selected English,
transliterated-Hindi, and Hindi-script patterns. This is not a medical triage model
and is not infallible: paraphrases can require model interpretation. No dosing or
diagnostic advice is generated. Ordinary empty calls and unavailable-slot calls
that the caller ends are abandoned, not automatically escalated.

## Caller, patient, and guardians

A phone can resolve one record; shared phones require distinguishing caller names.
The intended patient is separate from the caller. For child requests, the identified
caller's `guardian_of` list supplies permitted children; the child's stated name
selects among them. There are no Aarav/Arjun-specific exceptions. This also handles
Meera booking for Kabir in `cv_0006`. An unnamed child remains ambiguous even when
the caller is a valid guardian of several children.

`lookup_patient` always returns candidates. The policy decorates its result with
active appointments only for an authorized intended patient after the caller is
also returned by lookup. This solves the starter cancellation/rescheduling scripts,
which supply identity but no appointment ID, without guessing an ID or adding a
seventh tool. Knowing a name or an appointment ID is not authority. Claimed
friendship or neighbor status does not replace a guardian relationship.

These are synthetic-data caller assertions, not real authentication. An actual
clinic would require authenticated identity before releasing patient data.

## Conflicting concurrency and reset requirements

The PDF says two conversations racing for a slot cannot both succeed. The frozen
`schema.md` simultaneously requires every `/agent/run` to start from the shipped
clinic snapshot, and explicitly permits separate scripts to book the same slot.
We prioritize the executable evaluation contract: each run is isolated. Within
one shared `ClinicState`, the collision check and mutation are atomic under a lock.
Two threads sharing that state cannot both book the same slot; separate evaluation
snapshots can, by design. The UI labels the two-request scenario as state isolation.

A real shared schedule would require a separate shared-state mode with database
transactions/uniqueness constraints. Adding a global lock around independent
snapshots would not solve that problem. The in-memory dashboard store is separately
locked, bounded to 1,000 conversation IDs, and intended for one server process.

## Dates, windows, and corrections

All relative dates use the request's `today`. The clock is used only for dashboard
creation timestamps and elapsed metrics. Longer phrases such as "day after tomorrow"
are matched before their substrings. Later corrections override earlier values.
Date numbers are not clock times, and "book kar do" does not mean 14:00.
Invalid dates/times at tool boundaries return actionable errors.

Some scripts provide a morning/evening preference without a specific time or final
confirmation. Asking forever cannot complete a fixed script, so the explicit planner
chooses the earliest returned free slot in the requested window (morning before
12:00, evening from 16:00). An exact requested time is never silently substituted.
Unsupported/ambiguous expressions go to the model; parser hints are not availability.

Dr. Rao's Monday windows overlap at 11:45 in the supplied clinic data. Slot generation
deduplicates starts, preserving the actual schedule rather than inventing duplicate
capacity. Sundays have no doctor windows; 2 October is an explicit clinic holiday.
Doctor leave and occupied slots are checked again atomically during mutations.

## Fixed scripts and event order

The caller does not react to generated questions. We process read-only preparation
at each supplied turn but defer writes until the final turn, allowing later
corrections and emergency disclosures to prevent a write. Caller, agent and actual
tool events are recorded with turn indices. UI events live in dashboard records;
`/agent/run` retains the supplied output contract. We never reconstruct fictitious
intermediate assistant messages or distribute tools across turns arbitrarily.

## Providers, errors, and limits

Groq GPT-OSS-120B is the model planner, with GPT-OSS-20B retry and optional Gemini
2.0 Flash fallback via google-genai structured functions. Calls have explicit
30-second timeouts and bounded planning rounds. Model availability/rate limits can
still yield HTTP 503. During validation, provider-backed runs hit HTTP 429;
we do not label those runs successful or count them as determinism evidence.

Malformed calls are validated before execution: required fields, unknown arguments,
argument types, JSON object shape, and escalation enums. Repeated malformed message
structures trigger a human handoff. Failed calls are logged. An invalid JSON/array
argument is represented as an empty argument object with an explicit error because
the frozen log contract requires an object. Model prose cannot supply confirmations.

The API runs blocking SDK calls in FastAPI's worker pool, not its async event loop.
The frontend displays failed reads and resolution errors, refreshes server-computed
statistics, and supports narrow viewports. There is no claim of production privacy,
clinical certification, durable scheduling, or exhaustive natural-language coverage.

## Submission provenance

The PDF calls the brief confidential but also asks for a public code repository.
The code repository contains the supplied synthetic starter data required to run;
the assignment PDF and unrelated local files are not added. Publication and final
submission links must be verified by the candidate. Current coding-assistant prompts
are recorded verbatim; unavailable earlier prompts are not reconstructed from guesses.
