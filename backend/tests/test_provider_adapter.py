"""Validate the installed Gemini SDK adapter without a provider/network request."""
import json
from types import SimpleNamespace
from unittest.mock import patch

from app.agent.llm_client import GeminiClient, TOOL_DEFINITIONS_GROQ


def test_gemini_preserves_function_history_and_structured_calls():
    from google.genai import types
    client = GeminiClient.__new__(GeminiClient)
    captured = {}
    def generate_content(**kwargs):
        captured.update(kwargs)
        part = types.Part.from_function_call(name='search_slots', args={'doctor_id': 'dr_rao', 'date': '2026-10-03'})
        return SimpleNamespace(candidates=[SimpleNamespace(content=SimpleNamespace(parts=[part]))], usage_metadata=SimpleNamespace(total_token_count=123))
    client._client = SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))
    messages = [
        {'role': 'system', 'content': 'Front desk'},
        {'role': 'user', 'content': 'Book an appointment'},
        {'role': 'assistant', 'content': '', 'tool_calls': [{'id': 'first', 'function': {'name': 'lookup_patient', 'arguments': '{"phone":"9812200311"}'}}]},
        {'role': 'tool', 'tool_call_id': 'first', 'content': '{"candidates":[]}'},
    ]
    result, tokens = client.chat(messages, TOOL_DEFINITIONS_GROQ)
    assert tokens == 123
    assert result['tool_calls'][0]['function']['name'] == 'search_slots'
    assert json.loads(result['tool_calls'][0]['function']['arguments'])['date'] == '2026-10-03'
    assert captured['contents'][1].parts[0].function_call.name == 'lookup_patient'
    assert captured['contents'][2].parts[0].function_response.name == 'lookup_patient'
    assert len(captured['config'].tools[0].function_declarations) == 6
