"""Validate untrusted model calls before they reach the ground-truth layer."""
from app.agent.llm_client import TOOL_DEFINITIONS_GROQ

SCHEMAS = {t["function"]["name"]: t["function"]["parameters"] for t in TOOL_DEFINITIONS_GROQ}


def validate_arguments(name: str, arguments: dict) -> str | None:
    if name not in SCHEMAS:
        return f"Unknown tool {name!r}. Use one of: {', '.join(SCHEMAS)}."
    schema = SCHEMAS[name]
    for key in schema.get("required", []):
        if key not in arguments:
            return f"{name}: missing required argument {key}."
    for key, value in arguments.items():
        spec = schema["properties"].get(key)
        if spec is None:
            return f"{name}: unknown argument {key}."
        if not isinstance(value, str) or not value.strip():
            return f"{name}: {key} must be a non-empty string."
        if "enum" in spec and value not in spec["enum"]:
            return f"{name}: {key} must be one of {', '.join(spec['enum'])}."
    return None
