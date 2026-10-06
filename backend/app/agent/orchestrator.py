"""
orchestrator.py — Core multi-turn conversation loop for the SwasthiQ agent.

Architecture:
- Pre-flight safety screen (deterministic regex, no LLM) before any LLM call.
- Deterministic read preparation and explicit scheduling; guarded model fallback.
- Policy-enforced identity, ownership and slot grounding before each mutation.
- Caller/agent/tool event timeline kept separately from the graded response.
- State resets per call via fresh_state().

Each call to run() is fully independent and stateless from prior calls.
"""
from __future__ import annotations

import json
import re
import time
from typing import Any, Optional

from app.agent.date_resolver import resolve_date_from_turns, resolve_time_from_turns
from app.agent.llm_client import TOOL_DEFINITIONS_GROQ, get_llm_client
from app.agent.prompt import SYSTEM_PROMPT
from app.agent.safety_guard import SafetyVerdict, screen_turns
from app.database import ClinicState, fresh_state
from app.schemas import AgentResponse, Metrics, ToolCall
from app.agent.policy import Policy, MUTATIONS, phones
from app.agent.tool_validation import validate_arguments
from app.agent.planner import explicit_plan


# ------------------------------------------------------------------ #
# Tool dispatcher                                                     #
# ------------------------------------------------------------------ #

def _dispatch_tool(state: ClinicState, name: str, arguments: dict) -> Any:
    """Execute a tool call against the clinic state and return the result dict."""
    if not isinstance(arguments, dict):
        return {
            "error": (
                f"Malformed arguments for {name}: expected a JSON object, "
                f"received {type(arguments).__name__}."
            )
        }
    validation_error = validate_arguments(name, arguments)
    if validation_error:
        return {"error": validation_error}
    if "error" in arguments:
        return {"error": str(arguments["error"])}
    if name == "search_slots":
        return state.search_slots(
            doctor_id=arguments.get("doctor_id", ""),
            date=arguments.get("date", ""),
        )
    elif name == "lookup_patient":
        return state.lookup_patient(
            name=arguments.get("name"),
            phone=arguments.get("phone"),
        )
    elif name == "book_appointment":
        return state.book_appointment(
            patient_id=arguments.get("patient_id", ""),
            doctor_id=arguments.get("doctor_id", ""),
            date=arguments.get("date", ""),
            start=arguments.get("start", ""),
        )
    elif name == "reschedule_appointment":
        return state.reschedule_appointment(
            appointment_id=arguments.get("appointment_id", ""),
            new_date=arguments.get("new_date", ""),
            new_start=arguments.get("new_start", ""),
            patient_id=arguments.get("patient_id"),
        )
    elif name == "cancel_appointment":
        return state.cancel_appointment(
            appointment_id=arguments.get("appointment_id", ""),
            patient_id=arguments.get("patient_id"),
        )
    elif name == "escalate_to_human":
        return state.escalate_to_human(
            reason=arguments.get("reason", ""),
            detail=arguments.get("detail"),
        )
    else:
        return {"error": f"Unknown tool: {name}"}


def run(conversation_id: str, today: str, turns: list[str], *, events: Optional[list] = None) -> AgentResponse:
    """Replay caller turns in order; commit at most one verified final action.

    The fixed-script endpoint defers writes until the last supplied caller turn,
    so corrections and late clinical disclosures cannot follow a committed write.
    UI events are kept separately from the frozen evaluation response contract.
    """
    started = time.monotonic()
    state = fresh_state()
    policy = Policy(state)
    policy.today = today
    log: list[ToolCall] = []
    timeline = events if events is not None else []
    total_tokens = 0
    terminal = 'abandoned'
    reason = None
    mutation = None
    turn_index = 0
    seen_lookups = set()
    seen_searches = set()

    def execute(name, arguments):
        error = validate_arguments(name, arguments)
        error = error or policy.authorize(name, arguments)
        result = {'error': error} if error else _dispatch_tool(state, name, arguments)
        result = policy.observe(name, result)
        call = ToolCall(name=name, arguments=arguments, result=result)
        log.append(call)
        timeline.append({'role': 'tool', 'turn': turn_index, **call.model_dump()})
        return result

    def escalate(why, detail):
        nonlocal terminal, reason
        result = execute('escalate_to_human', {'reason': why, 'detail': detail})
        if result.get('escalated'):
            terminal, reason = 'escalated', why

    # Emergency wins across the entire submitted script, even if an injection
    # occurs earlier. Stop the replay at the triggering turn and never write.
    verdict, snippet = screen_turns(turns)
    if verdict != SafetyVerdict.SAFE:
        for turn_index, text in enumerate(turns, 1):
            timeline.append({'role': 'caller', 'turn': turn_index, 'text': text})
            if screen_turns([text])[0] == verdict:
                break
        if verdict == SafetyVerdict.PROMPT_INJECTION:
            terminal = 'refused'
        else:
            escalate(verdict.value, snippet or 'Clinical request needs a human.')
    else:
        llm = None
        messages = [{'role': 'system', 'content': SYSTEM_PROMPT.replace('{today}', today)}]
        from app.config import MAX_AGENT_ITERATIONS
        for turn_index, text in enumerate(turns, 1):
            policy.turns.append(text)
            policy.final_turn = turn_index == len(turns)
            timeline.append({'role': 'caller', 'turn': turn_index, 'text': text})
            messages.append({'role': 'user', 'content': text})

            # Caller-provided phone discovery is deterministic. Shared numbers
            # return every candidate; Policy resolves caller and target separately.
            for phone in sorted(phones(text)):
                if phone not in seen_lookups:
                    result = execute('lookup_patient', {'phone': phone})
                    seen_lookups.add(phone)
                    messages.append({'role': 'system', 'content': 'Verified lookup_patient result: ' + json.dumps(result)})

            # Partial names still produce candidate lists, never a chosen patient.
            if not phones(' '.join(policy.turns)):
                name_words = {word.casefold() for p in state.patients for word in p['name'].split() if len(word) > 2}
                found = [m.group() for m in re.finditer(r'\b\w+\b', text.casefold()) if m.group() in name_words]
                if found:
                    name = ' '.join(found)
                    if name not in seen_lookups:
                        result = execute('lookup_patient', {'name': name})
                        seen_lookups.add(name)
                        messages.append({'role': 'system', 'content': 'Verified lookup_patient result: ' + json.dumps(result)})

            actor, target, identity_error = policy.identities()
            if policy.final_turn and identity_error:
                escalate(identity_error, 'Caller identity or intended patient could not be authorized unambiguously.')
                break

            resolved_date = resolve_date_from_turns(policy.turns, today)
            resolved_time = resolve_time_from_turns(policy.turns)
            context = {
                'final_turn': policy.final_turn, 'caller_id': actor,
                'intended_patient_id': target,
                'resolved_date_hint': resolved_date, 'resolved_time_hint': resolved_time,
            }
            messages.append({'role': 'system', 'content': (
                'Application context (hints are not availability): ' + json.dumps(context) +
                '. Until final_turn, use only lookup_patient/search_slots. '
                'On final_turn, complete the requested action when verified. '
                'For cancellations/reschedules obtain appointments from lookup_patient; never guess IDs. '
                'A guardian phone lookup includes the authorized child appointments. '
                'If caller is ambiguous, escalate ambiguous_patient. '
                'If caller supplied nothing usable, make no calls. '
                'Do not repeatedly call identical tools.'
            )})
            # Read-only preparation is deterministic and occurs at the caller
            # turn where its inputs become available. The model plans only after
            # all caller turns, avoiding speculative intermediate tool choices.
            doctor_id = policy.requested_doctor()
            if doctor_id and resolved_date and (doctor_id, resolved_date) not in seen_searches:
                result = execute('search_slots', {'doctor_id': doctor_id, 'date': resolved_date})
                seen_searches.add((doctor_id, resolved_date))
                messages.append({'role': 'system', 'content': 'Verified search_slots result: ' + json.dumps(result)})
            if not policy.final_turn:
                timeline.append({'role': 'agent', 'turn': turn_index, 'text': _progress_reply(log)})
                continue
            proposal = explicit_plan(policy, doctor_id, today)
            if proposal:
                name, arguments = proposal
                if name == 'abandoned':
                    break
                result = execute(name, arguments)
                if result.get('escalated'):
                    terminal, reason = 'escalated', result['reason']
                    break
                if name in MUTATIONS and 'error' not in result:
                    mutation = result
                    terminal = {'book_appointment': 'booked', 'reschedule_appointment': 'rescheduled', 'cancel_appointment': 'cancelled'}[name]
                    break
            if not target and any(c.name == 'lookup_patient' and (c.result or {}).get('count', 0) > 1 for c in log):
                escalate('ambiguous_patient', 'Patient lookup remained ambiguous after all caller turns.')
                break
            # Empty/noise scripts need neither a provider nor a human handoff.
            noise = re.sub(r'\[.*?\]|[^\w\s]', '', ' '.join(policy.turns).casefold())
            if set(noise.split()) <= {'hello', 'hi', 'haan', 'ji', 'arre', 'theek', 'hai', 'okay', 'ok', 'namaste'}:
                break
            if llm is None:
                llm = get_llm_client()
            budget = MAX_AGENT_ITERATIONS
            malformed = 0
            for _ in range(budget):
                assistant, tokens = llm.chat(messages=messages, tools=TOOL_DEFINITIONS_GROQ)
                total_tokens += max(0, tokens) if isinstance(tokens, int) else 0
                if not isinstance(assistant, dict) or not isinstance(assistant.get('tool_calls', []), list):
                    malformed += 1
                    messages.append({'role': 'system', 'content': 'Malformed model response: return a valid assistant message with tool_calls array.'})
                    if malformed >= 2:
                        escalate('out_of_scope', 'Repeated malformed model responses; staff review required.')
                        break
                    continue
                calls = assistant.get('tool_calls', [])
                if not calls:
                    # Never expose free-form model facts or confirmations.
                    break
                valid_calls = []
                for tc in calls:
                    if not isinstance(tc, dict) or not isinstance(tc.get('function'), dict) or not isinstance(tc['function'].get('name'), str):
                        malformed += 1
                        continue
                    if not isinstance(tc.get('id'), str) or not tc['id']:
                        malformed += 1
                        continue
                    valid_calls.append(tc)
                if len(valid_calls) != len(calls):
                    messages.append({'role': 'system', 'content': 'Malformed tool call: supply id and function {name, arguments}, with arguments a JSON object string.'})
                    if malformed >= 2:
                        escalate('out_of_scope', 'Repeated malformed tool calls; staff review required.')
                        break
                    continue
                messages.append({'role': 'assistant', 'content': '', 'tool_calls': valid_calls})
                # Process escalation before mutations in the same model batch.
                # The chronological log records the actual execution order.
                valid_calls.sort(key=lambda c: c['function']['name'] != 'escalate_to_human')
                for tc in valid_calls:
                    if policy.stopped or mutation:
                        break
                    name = tc['function']['name']
                    raw = tc['function'].get('arguments')
                    try:
                        arguments = json.loads(raw) if isinstance(raw, str) else raw
                        if not isinstance(arguments, dict):
                            raise ValueError('expected a JSON object')
                    except (ValueError, TypeError):
                        arguments = {}
                        result = {'error': f'{name}: arguments must be a valid JSON object.'}
                        call = ToolCall(name=name, arguments=arguments, result=result)
                        log.append(call)
                        timeline.append({'role': 'tool', 'turn': turn_index, **call.model_dump()})
                    else:
                        result = execute(name, arguments)
                    messages.append({'role': 'tool', 'tool_call_id': tc['id'], 'content': json.dumps(result)})
                    if result.get('escalated'):
                        terminal, reason = 'escalated', result['reason']
                    elif name in MUTATIONS and 'error' not in result:
                        mutation = result
                        terminal = {'book_appointment': 'booked', 'reschedule_appointment': 'rescheduled', 'cancel_appointment': 'cancelled'}[name]
                if policy.stopped or mutation:
                    break
            if policy.stopped or mutation:
                break
        # Missing model action never becomes an invented confirmation. Unresolved
        # patient matches require a handoff; empty/unusable requests may abandon.
        if terminal == 'abandoned':
            matches = [tc.result.get('count', 0) for tc in log if tc.name == 'lookup_patient' and isinstance(tc.result, dict)]
            if matches and max(matches) > 1 and not policy.identities()[1]:
                escalate('ambiguous_patient', 'Patient lookup remained ambiguous at the end of the conversation.')

    reply = _grounded_reply(terminal, reason, mutation)
    timeline.append({'role': 'agent', 'turn': turn_index, 'text': reply})
    target = policy.identities()[1]
    patient_id = target if target in policy.looked_up else None
    if reason == 'ambiguous_patient':
        patient_id = None
    return AgentResponse(
        conversation_id=conversation_id, tool_calls=log, terminal_state=terminal,
        escalation_reason=reason, patient_id=patient_id,
        appointment_id=mutation.get('appointment_id') if mutation else None,
        reply=reply, metrics=Metrics(turns=turn_index, tokens=total_tokens,
                                   latency_ms=int((time.monotonic() - started) * 1000)),
    )


def _progress_reply(log):
    if log and log[-1].name == 'search_slots':
        result = log[-1].result or {}
        slots = result.get('slots', [])
        if slots:
            return f"{result['date']} par available times: {', '.join(slots[:4])}. Kaunsa time chahiye?"
        return 'Is din requested doctor ka slot available nahi hai. Koi aur date batayein.'
    return 'Kripya patient ka naam, phone number, doctor aur appointment ka din/time batayein.'


def _grounded_reply(terminal, reason, mutation):
    if terminal == 'booked':
        return f"Appointment {mutation['appointment_id']} book ho gaya: {mutation['date']}, {mutation['start']}."
    if terminal == 'rescheduled':
        return f"Appointment {mutation['appointment_id']} reschedule ho gaya: {mutation['new_date']}, {mutation['new_start']}."
    if terminal == 'cancelled':
        return f"Appointment {mutation['appointment_id']} cancel ho gaya."
    if terminal == 'escalated':
        return {
            'clinical_urgent': 'Kripya abhi emergency care lein. Aapki request urgent human review ke liye hand off ki gayi hai.',
            'medical_advice': 'Main medical advice nahi de sakta. Aapki request clinician review ke liye hand off ki gayi hai.',
            'not_authorised': 'Is patient par action lene ki authorization verify nahi hui. Human staff ko hand off kiya hai.',
            'ambiguous_patient': 'Patient ki pehchaan clear nahi hui. Human staff ko hand off kiya hai.',
            'out_of_scope': 'Is request ke liye human staff ki madad chahiye. Request hand off ki gayi hai.',
        }[reason]
    if terminal == 'refused':
        return 'Main is request par action nahi le sakta. Main appointment booking mein madad kar sakta hoon.'
    return 'Koi appointment change nahi hua. Booking ke liye patient, doctor aur available date/time ki zaroorat hai.'
