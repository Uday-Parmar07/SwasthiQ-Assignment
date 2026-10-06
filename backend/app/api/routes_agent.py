"""FastAPI route for POST /agent/run."""
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from app.schemas import AgentRequest, AgentResponse
from app.agent import orchestrator
from app.api.routes_queue import store_result

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/agent/run", response_model=AgentResponse)
def agent_run(request: AgentRequest) -> AgentResponse:
    """
    The single graded endpoint. Processes a full conversation and returns
    a schema.md-compliant response.
    """
    try:
        events = []
        result = orchestrator.run(
            conversation_id=request.conversation_id,
            today=request.today,
            turns=request.turns,
            events=events,
        )
        record = result.model_dump()
        detail = next((call.arguments.get('detail', '') for call in result.tool_calls
                       if call.name == 'escalate_to_human'), '')
        preview = next((turn for turn in request.turns if detail and detail in turn),
                       request.turns[0] if request.turns else '')
        record.update(raw_turns=request.turns, today=request.today, events=events,
                      caller_preview=preview,
                      created_at=datetime.now(timezone.utc).isoformat())
        store_result(request.conversation_id, record)
        return result
    except RuntimeError as exc:
        # A missing/invalid provider key must be actionable, not an opaque 500.
        logger.exception("Agent run failed during provider or grounding validation")
        raise HTTPException(status_code=503, detail="Language-model provider unavailable. Check the configured key and retry.") from exc
    except Exception as exc:
        # Provider SDK/network failures are service errors, not malformed caller
        # requests. Keep the internal exception out of the public response.
        logger.exception("Unexpected agent run failure")
        raise HTTPException(
            status_code=502,
            detail="The configured language-model provider could not complete the request.",
        ) from exc
