"""
llm_client.py — Groq / Gemini LLM client with automatic fallback.

Uses Groq as primary (free tier, high speed, tool calling).
Falls back to Google Gemini if GROQ_API_KEY is absent.
temperature=0.0 is enforced for determinism.
"""
from __future__ import annotations

import json
from typing import Any
from functools import lru_cache

from app.config import (
    GEMINI_API_KEY,
    GEMINI_MODEL,
    GROQ_API_KEY,
    GROQ_MODEL_FAST,
    GROQ_MODEL_PRIMARY,
    LLM_TEMPERATURE,
)


# ------------------------------------------------------------------ #
# Tool definitions for LLM function calling                           #
# ------------------------------------------------------------------ #

TOOL_DEFINITIONS_GROQ = [
    {
        "type": "function",
        "function": {
            "name": "lookup_patient",
            "description": "Resolve caller and patient records. Returns all candidates, never guesses. Authorized intended patients include their active appointments with IDs; use these for cancellation/rescheduling.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Patient name or partial name"},
                    "phone": {"type": "string", "description": "10-digit phone number"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_slots",
            "description": "Return available 15-minute appointment slots for a doctor on a specific date.",
            "parameters": {
                "type": "object",
                "properties": {
                    "doctor_id": {"type": "string", "description": "e.g. dr_rao or dr_sethi"},
                    "date": {"type": "string", "description": "YYYY-MM-DD"},
                },
                "required": ["doctor_id", "date"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "book_appointment",
            "description": "Create a new appointment in a free slot.",
            "parameters": {
                "type": "object",
                "properties": {
                    "patient_id": {"type": "string"},
                    "doctor_id": {"type": "string"},
                    "date": {"type": "string", "description": "YYYY-MM-DD"},
                    "start": {"type": "string", "description": "HH:MM 24-hour"},
                },
                "required": ["patient_id", "doctor_id", "date", "start"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "reschedule_appointment",
            "description": "Move an existing appointment to a new slot.",
            "parameters": {
                "type": "object",
                "properties": {
                    "appointment_id": {"type": "string"},
                    "new_date": {"type": "string", "description": "YYYY-MM-DD"},
                    "new_start": {"type": "string", "description": "HH:MM 24-hour"},
                    "patient_id": {"type": "string", "description": "Verified patient who owns the appointment"},
                },
                "required": ["appointment_id", "new_date", "new_start", "patient_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cancel_appointment",
            "description": "Cancel an existing appointment.",
            "parameters": {
                "type": "object",
                "properties": {
                    "appointment_id": {"type": "string"},
                    "patient_id": {"type": "string", "description": "Verified patient who owns the appointment"},
                },
                "required": ["appointment_id", "patient_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "escalate_to_human",
            "description": (
                "Hand the conversation to a human agent. "
                "reason must be exactly one of: "
                "clinical_urgent | medical_advice | not_authorised | ambiguous_patient | out_of_scope"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {
                        "type": "string",
                        "enum": [
                            "clinical_urgent", "medical_advice",
                            "not_authorised", "ambiguous_patient", "out_of_scope",
                        ],
                    },
                    "detail": {"type": "string", "description": "Short explanation"},
                },
                "required": ["reason"],
            },
        },
    },
]


# ------------------------------------------------------------------ #
# Groq client wrapper                                                 #
# ------------------------------------------------------------------ #

class GroqClient:
    def __init__(self) -> None:
        import httpx
        from groq import Groq  # type: ignore[import]
        # Groq 0.11's default transport still passes the removed `proxies`
        # argument when paired with httpx 0.28 (required by google-genai).
        # Supplying the client explicitly keeps both dependencies compatible.
        self._client = Groq(api_key=GROQ_API_KEY, http_client=httpx.Client(timeout=30.0), timeout=30.0, max_retries=0)
        self._model = GROQ_MODEL_PRIMARY

    def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
    ) -> tuple[dict, int]:
        """
        Returns (message dict, total_tokens).
        """
        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "temperature": LLM_TEMPERATURE,
            "max_tokens": 2048,
            "extra_body": {"reasoning_effort": "low"},
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        try:
            resp = self._client.chat.completions.create(**kwargs)
        except Exception as primary_error:
            # Retry once with the smaller current Groq model. Preserve the
            # provider error if both attempts fail so the API does not look
            # like an unexplained internal server error.
            kwargs["model"] = GROQ_MODEL_FAST
            try:
                resp = self._client.chat.completions.create(**kwargs)
            except Exception as retry_error:
                if GEMINI_API_KEY:
                    try:
                        return GeminiClient().chat(messages, tools)
                    except Exception:
                        pass
                raise RuntimeError(
                    "Groq request failed for "
                    f"{GROQ_MODEL_PRIMARY} and {GROQ_MODEL_FAST}: "
                    f"{type(retry_error).__name__}: {retry_error}"
                ) from retry_error

        msg = resp.choices[0].message
        tokens = resp.usage.total_tokens if resp.usage else 0
        return _groq_msg_to_dict(msg), tokens


def _groq_msg_to_dict(msg: Any) -> dict:
    d: dict[str, Any] = {"role": msg.role, "content": msg.content or ""}
    if msg.tool_calls:
        d["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.function.name,
                    "arguments": tc.function.arguments,
                },
            }
            for tc in msg.tool_calls
        ]
    return d


# ------------------------------------------------------------------ #
# Gemini client wrapper                                               #
# ------------------------------------------------------------------ #

class GeminiClient:
    """google-genai adapter preserving function calls and function responses."""
    def __init__(self) -> None:
        from google import genai
        from google.genai import types
        self._client = genai.Client(api_key=GEMINI_API_KEY, http_options=types.HttpOptions(timeout=30000))

    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> tuple[dict, int]:
        from google.genai import types
        contents = []
        names = {}
        for message in messages:
            role = message['role']
            parts = []
            if role == 'system':
                # Dynamic application context remains at its chronological position.
                if contents:
                    contents.append(types.Content(role='user', parts=[types.Part.from_text(text='Application context: ' + message['content'])]))
                continue
            if role == 'tool':
                parts = [types.Part.from_function_response(name=names[message['tool_call_id']], response=json.loads(message['content']))]
                role = 'user'
            else:
                if message.get('content'):
                    parts.append(types.Part.from_text(text=message['content']))
                for call in message.get('tool_calls', []):
                    fn = call['function']
                    names[call['id']] = fn['name']
                    parts.append(types.Part.from_function_call(name=fn['name'], args=json.loads(fn['arguments'])))
                role = 'model' if role == 'assistant' else 'user'
            if parts:
                contents.append(types.Content(role=role, parts=parts))
        declarations = [types.FunctionDeclaration(name=t['function']['name'], description=t['function']['description'], parameters=t['function']['parameters']) for t in (tools or [])]
        response = self._client.models.generate_content(
            model=GEMINI_MODEL, contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=messages[0]['content'], temperature=LLM_TEMPERATURE,
                max_output_tokens=1024, tools=[types.Tool(function_declarations=declarations)] if declarations else None,
                automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            ),
        )
        parts = response.candidates[0].content.parts if response.candidates and response.candidates[0].content else []
        result = {'role': 'assistant', 'content': ''.join(p.text or '' for p in parts)}
        calls = []
        for i, part in enumerate(parts):
            if part.function_call:
                calls.append({'id': f'gemini_{len(messages)}_{i}', 'type': 'function', 'function': {
                    'name': part.function_call.name, 'arguments': json.dumps(dict(part.function_call.args or {})),
                }})
        if calls: result['tool_calls'] = calls
        return result, (response.usage_metadata.total_token_count or 0) if response.usage_metadata else 0


# ------------------------------------------------------------------ #
# Factory                                                             #
# ------------------------------------------------------------------ #

@lru_cache(maxsize=1)
def get_llm_client():
    """Return a Groq client if key is configured, else Gemini."""
    if GROQ_API_KEY:
        return GroqClient()
    if GEMINI_API_KEY:
        return GeminiClient()
    raise RuntimeError(
        "No LLM API key configured. Set GROQ_API_KEY or GEMINI_API_KEY in .env"
    )
