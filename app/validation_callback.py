"""Validation callback handling for async LLM validation flow."""

import json
import logging
from typing import Dict, Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.validation_state import PendingValidationState, ValidationStateManager
from app.config import config

logger = logging.getLogger(__name__)

# Router for internal endpoints
router = APIRouter(prefix="/internal", tags=["internal"])

# Global state manager (lazy-initialized)
_state_manager: ValidationStateManager | None = None


class ValidationCallbackPayload(BaseModel):
    """Payload received from LLM proxy callback."""
    job_id: str
    status: str
    result: Optional[Dict[str, Any]] = None
    error: Optional[Dict[str, Any]] = None
    metadata: Optional[Dict[str, Any]] = None


def get_state_manager() -> ValidationStateManager:
    """Get or create the global state manager."""
    global _state_manager

    if _state_manager is None:
        # Import redis here to avoid circular imports
        import redis
        redis_client = redis.Redis(
            host=config.REDIS_HOST,
            port=config.REDIS_PORT,
            password=config.REDIS_PASSWORD,
            decode_responses=False,
            socket_connect_timeout=5
        )
        _state_manager = ValidationStateManager(
            redis_client=redis_client,
            ttl=getattr(config, 'OCR_VALIDATION_STATE_TTL', 300)
        )

    return _state_manager


def set_state_manager(manager: ValidationStateManager) -> None:
    """Set the state manager (for testing)."""
    global _state_manager
    _state_manager = manager


async def continue_after_validation(
    state: PendingValidationState,
    is_valid: bool,
    confidence: float,
    reason: str
) -> None:
    """
    Continue processing after validation callback.

    This function handles the next steps after receiving validation result:
    - If valid: record result and proceed to next image or complete
    - If invalid: try next tier or mark as failed

    Args:
        state: The pending validation state
        is_valid: Whether the OCR output was valid
        confidence: Confidence score (0.0-1.0)
        reason: Reason for validation result
    """
    # Import here to avoid circular imports
    from app.continue_processing import process_validation_result

    await process_validation_result(
        state=state,
        is_valid=is_valid,
        confidence=confidence,
        reason=reason
    )


def _parse_validation_result(payload: ValidationCallbackPayload) -> tuple[bool, float, str]:
    """
    Parse validation result from callback payload.

    Args:
        payload: The callback payload from LLM proxy

    Returns:
        Tuple of (is_valid, confidence, reason)
    """
    # If status is failed, treat as invalid
    if payload.status == "failed":
        error_msg = "LLM validation failed"
        if payload.error:
            error_msg = payload.error.get("message", error_msg)[:200]
        return False, 0.0, error_msg

    # Try to parse result content
    if not payload.result or "content" not in payload.result:
        return False, 0.0, "No validation result content"

    content = payload.result["content"]

    try:
        # Parse JSON from content
        validation = json.loads(content)
        is_valid = validation.get("is_valid", False)
        confidence = float(validation.get("confidence", 0.5))
        reason = validation.get("reason", "")[:200]

        # Clamp confidence to 0.0-1.0
        confidence = max(0.0, min(1.0, confidence))

        return is_valid, confidence, reason

    except (json.JSONDecodeError, TypeError, ValueError) as e:
        logger.warning(f"Failed to parse validation result: {e}")
        return False, 0.0, f"Failed to parse validation result: {str(e)[:100]}"


@router.post("/validation/callback")
async def validation_callback(payload: ValidationCallbackPayload):
    """
    Receive validation callback from LLM proxy.

    This endpoint is called by the LLM proxy when validation is complete.
    """
    # Validate metadata
    if not payload.metadata:
        raise HTTPException(status_code=400, detail="Missing metadata in callback")

    validation_state_key = payload.metadata.get("validation_state_key")
    if not validation_state_key:
        raise HTTPException(status_code=400, detail="Missing validation_state_key in metadata")

    logger.info(
        f"Received validation callback [job_id={payload.job_id}, "
        f"status={payload.status}, state_key={validation_state_key}]"
    )

    # Load state from Redis
    state_manager = get_state_manager()
    state = state_manager.get(validation_state_key)

    if state is None:
        logger.warning(f"Validation state not found or expired: {validation_state_key}")
        raise HTTPException(status_code=404, detail="Validation state not found or expired")

    # Parse validation result
    is_valid, confidence, reason = _parse_validation_result(payload)

    logger.info(
        f"Validation result [state_key={validation_state_key}, "
        f"is_valid={is_valid}, confidence={confidence}, reason={reason[:50]}...]"
    )

    # Delete state from Redis (we've loaded it and will process it)
    state_manager.delete(validation_state_key)

    # Continue processing
    await continue_after_validation(
        state=state,
        is_valid=is_valid,
        confidence=confidence,
        reason=reason
    )

    return {"status": "ok", "processed": True}
