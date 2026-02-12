"""Continuation logic after validation callback."""

import logging
import uuid
from datetime import datetime
from typing import Dict, Any, List, Optional

from app.validation_state import PendingValidationState
from app.config import config
from app.queue_client import queue_client
from app.text_utils import truncate_text

logger = logging.getLogger(__name__)


def _build_image_result(
    image_index: int,
    ocr_text: str,
    tier_name: str,
    is_valid: bool,
    confidence: float,
    reason: str,
    language: str,
    error: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Build an image result dict for the completion message.

    Args:
        image_index: Index of the image
        ocr_text: The extracted OCR text
        tier_name: Name of the tier that produced the result
        is_valid: Whether the OCR output was valid
        confidence: Confidence score (0.0-1.0)
        reason: Reason for validation result
        language: Language hint used
        error: Optional error dict

    Returns:
        Result dict matching queue-flow schema
    """
    # Truncate text if needed
    truncated_text, was_truncated = truncate_text(ocr_text, config.OCR_MAX_TEXT_BYTES)

    return {
        "index": image_index,
        "ocr_text": truncated_text,
        "truncated": was_truncated,
        "meta": {
            "language": language,
            "confidence": confidence,
            "text_len": len(truncated_text.encode("utf-8")),
            "is_valid": is_valid,
            "tier": tier_name,
            "validation_reason": reason[:200] if reason else None
        },
        "error": error
    }


async def _create_completion_and_send(
    original_job: Dict[str, Any],
    results: List[Dict[str, Any]],
    error: Optional[Dict[str, Any]] = None
) -> None:
    """
    Create and send a completion message to the reply queue.

    Args:
        original_job: The original OCR request job
        results: List of image results
        error: Optional top-level error (for job-level failures)
    """
    # Determine status based on whether any image is valid
    status = "failed"
    for result in results:
        if result.get("meta", {}).get("is_valid", False):
            status = "success"
            break

    # Generate new job_id for completion event
    completion_job_id = str(uuid.uuid4())

    completion_message = {
        "schema_version": 1,
        "job_id": completion_job_id,
        "workflow_id": original_job["workflow_id"],
        "job_type": "ocr.completed",
        "source": "jarvis-ocr-service",
        "target": original_job.get("source", "unknown"),
        "created_at": datetime.utcnow().isoformat() + "Z",
        "attempt": 1,
        "reply_to": None,
        "payload": {
            "status": status,
            "results": results,
            "artifact_ref": None,
            "error": error if status == "failed" and error else {"message": None, "code": None}
        },
        "trace": {
            "request_id": original_job.get("trace", {}).get("request_id"),
            "parent_job_id": original_job["job_id"]
        }
    }

    reply_to = original_job.get("reply_to")
    if reply_to:
        logger.debug(
            f"Completion message trace: parent_job_id={completion_message['trace']['parent_job_id']}, "
            f"original_job_id={original_job.get('job_id')}"
        )
        success = queue_client.enqueue(reply_to, completion_message)
        if success:
            logger.info(
                f"Sent completion to {reply_to} [job_id={completion_job_id}, "
                f"workflow_id={original_job['workflow_id']}, status={status}]"
            )
        else:
            logger.error(
                f"Failed to send completion to {reply_to} "
                f"[job_id={completion_job_id}]"
            )
    else:
        logger.warning(
            f"No reply_to queue specified, completion not sent "
            f"[job_id={completion_job_id}]"
        )


async def _process_with_next_tier(
    state: PendingValidationState,
    next_tier: str,
    remaining_tiers: List[str]
) -> None:
    """
    Process the image with the next tier in the fallback chain.

    This function enqueues a new validation job for the next tier.

    Args:
        state: Current validation state
        next_tier: Name of the next tier to try
        remaining_tiers: Tiers remaining after next_tier
    """
    from app.llm_queue_client import get_llm_queue_client
    from app.validation_callback import get_state_manager
    from app.tier_mapping import tier_to_provider

    logger.info(
        f"Trying next tier {next_tier} for image {state.image_index} "
        f"[job_id={state.original_job.get('job_id')}]"
    )

    # Get the image and process with next tier
    # For async flow, we need to:
    # 1. Get image bytes from the original job
    # 2. Process with the next tier provider
    # 3. Save new state and enqueue validation

    # For now, we need to re-process the image with the next tier
    # This requires importing the provider manager and doing OCR
    # Then enqueueing another validation job

    from app.image_resolver import resolve_image, ImageResolverError
    from app.provider_manager import ProviderManager
    from app.text_utils import normalize_text
    import base64

    image_refs = state.original_job.get("payload", {}).get("image_refs", [])
    image_ref = None
    for ref in image_refs:
        if ref.get("index") == state.image_index:
            image_ref = ref
            break

    if not image_ref:
        logger.error(f"Image ref not found for index {state.image_index}")
        # Mark as failed and complete
        result = _build_image_result(
            image_index=state.image_index,
            ocr_text="",
            tier_name=next_tier,
            is_valid=False,
            confidence=0.0,
            reason="Image reference not found",
            language=state.original_job.get("payload", {}).get("options", {}).get("language", "en"),
            error={"code": "image_not_found", "message": "Image reference not found"}
        )
        all_results = state.processed_results + [result]
        await _create_completion_and_send(state.original_job, all_results)
        return

    try:
        image_bytes, content_type = resolve_image(image_ref)
        image_base64 = base64.b64encode(image_bytes).decode('utf-8')
    except ImageResolverError as e:
        logger.error(f"Failed to resolve image: {e}")
        result = _build_image_result(
            image_index=state.image_index,
            ocr_text="",
            tier_name=next_tier,
            is_valid=False,
            confidence=0.0,
            reason=str(e)[:200],
            language=state.original_job.get("payload", {}).get("options", {}).get("language", "en"),
            error={"code": "image_not_found", "message": str(e)[:200]}
        )
        all_results = state.processed_results + [result]
        await _create_completion_and_send(state.original_job, all_results)
        return

    # Process with next tier
    try:
        provider_manager = ProviderManager()
        provider_name = tier_to_provider(next_tier)
        language = state.original_job.get("payload", {}).get("options", {}).get("language", "en")

        ocr_result, _ = await provider_manager.process_image(
            image_base64=image_base64,
            provider_name=provider_name,
            language_hints=[language] if language else None,
            return_boxes=False,
            mode="document"
        )

        ocr_text = normalize_text(ocr_result.text)

        # Create new validation state
        new_validation_job_id = f"val-{uuid.uuid4()}"
        new_state = PendingValidationState(
            original_job=state.original_job,
            image_index=state.image_index,
            tier_name=next_tier,
            ocr_text=ocr_text,
            remaining_tiers=remaining_tiers,
            processed_results=state.processed_results,
            validation_job_id=new_validation_job_id,
            created_at=datetime.utcnow().isoformat() + "Z"
        )

        # Save state and enqueue validation
        state_manager = get_state_manager()
        state_manager.save(new_state)

        llm_client = get_llm_queue_client()
        callback_url = f"{config.OCR_PUBLIC_URL}/internal/validation/callback"
        await llm_client.enqueue(new_state, callback_url)

        logger.info(
            f"Enqueued validation for tier {next_tier} "
            f"[validation_job_id={new_validation_job_id}]"
        )

    except Exception as e:
        logger.error(f"Failed to process with tier {next_tier}: {e}")
        # If this tier fails, try next or mark as failed
        if remaining_tiers:
            await _process_with_next_tier(state, remaining_tiers[0], remaining_tiers[1:])
        else:
            result = _build_image_result(
                image_index=state.image_index,
                ocr_text="",
                tier_name=next_tier,
                is_valid=False,
                confidence=0.0,
                reason=f"Tier failed: {str(e)[:150]}",
                language=state.original_job.get("payload", {}).get("options", {}).get("language", "en"),
                error={"code": "ocr_engine_error", "message": str(e)[:200]}
            )
            all_results = state.processed_results + [result]
            await _create_completion_and_send(state.original_job, all_results)


async def _process_next_image(
    state: PendingValidationState,
    current_result: Dict[str, Any],
    next_image_index: int
) -> None:
    """
    Process the next image in a multi-image job.

    Args:
        state: Current validation state
        current_result: Result for the current image
        next_image_index: Index of the next image to process
    """
    from app.llm_queue_client import get_llm_queue_client
    from app.validation_callback import get_state_manager
    from app.image_resolver import resolve_image, ImageResolverError
    from app.provider_manager import ProviderManager
    from app.text_utils import normalize_text
    from app.tier_mapping import get_tier_order
    import base64

    logger.info(
        f"Processing next image {next_image_index} "
        f"[job_id={state.original_job.get('job_id')}]"
    )

    # Add current result to processed results
    all_processed = state.processed_results + [current_result]

    # Get next image ref
    image_refs = state.original_job.get("payload", {}).get("image_refs", [])
    image_ref = None
    for ref in image_refs:
        if ref.get("index") == next_image_index:
            image_ref = ref
            break

    if not image_ref:
        logger.error(f"Image ref not found for index {next_image_index}")
        # Complete with what we have
        await _create_completion_and_send(state.original_job, all_processed)
        return

    # Get enabled tiers for fresh start
    enabled_tiers = config.get_enabled_tiers()
    tier_order = get_tier_order(enabled_tiers)

    if not tier_order:
        logger.error("No enabled tiers available")
        await _create_completion_and_send(state.original_job, all_processed)
        return

    first_tier = tier_order[0]
    remaining_tiers = tier_order[1:]

    try:
        image_bytes, content_type = resolve_image(image_ref)
        image_base64 = base64.b64encode(image_bytes).decode('utf-8')
    except ImageResolverError as e:
        logger.error(f"Failed to resolve image {next_image_index}: {e}")
        result = _build_image_result(
            image_index=next_image_index,
            ocr_text="",
            tier_name="unknown",
            is_valid=False,
            confidence=0.0,
            reason=str(e)[:200],
            language=state.original_job.get("payload", {}).get("options", {}).get("language", "en"),
            error={"code": "image_not_found", "message": str(e)[:200]}
        )
        all_processed.append(result)

        # Check if more images
        image_count = state.original_job.get("payload", {}).get("image_count", 1)
        if next_image_index + 1 < image_count:
            # Create dummy state to continue
            dummy_state = PendingValidationState(
                original_job=state.original_job,
                image_index=next_image_index,
                tier_name="unknown",
                ocr_text="",
                remaining_tiers=[],
                processed_results=all_processed,
                validation_job_id=f"val-{uuid.uuid4()}",
                created_at=datetime.utcnow().isoformat() + "Z"
            )
            await _process_next_image(dummy_state, result, next_image_index + 1)
        else:
            await _create_completion_and_send(state.original_job, all_processed)
        return

    # Process with first tier
    try:
        from app.tier_mapping import tier_to_provider

        provider_manager = ProviderManager()
        provider_name = tier_to_provider(first_tier)
        language = state.original_job.get("payload", {}).get("options", {}).get("language", "en")

        ocr_result, _ = await provider_manager.process_image(
            image_base64=image_base64,
            provider_name=provider_name,
            language_hints=[language] if language else None,
            return_boxes=False,
            mode="document"
        )

        ocr_text = normalize_text(ocr_result.text)

        # Create new validation state
        new_validation_job_id = f"val-{uuid.uuid4()}"
        new_state = PendingValidationState(
            original_job=state.original_job,
            image_index=next_image_index,
            tier_name=first_tier,
            ocr_text=ocr_text,
            remaining_tiers=remaining_tiers,
            processed_results=all_processed,
            validation_job_id=new_validation_job_id,
            created_at=datetime.utcnow().isoformat() + "Z"
        )

        # Save state and enqueue validation
        state_manager = get_state_manager()
        state_manager.save(new_state)

        llm_client = get_llm_queue_client()
        callback_url = f"{config.OCR_PUBLIC_URL}/internal/validation/callback"
        await llm_client.enqueue(new_state, callback_url)

        logger.info(
            f"Enqueued validation for image {next_image_index} tier {first_tier} "
            f"[validation_job_id={new_validation_job_id}]"
        )

    except Exception as e:
        logger.error(f"Failed to process image {next_image_index}: {e}")
        result = _build_image_result(
            image_index=next_image_index,
            ocr_text="",
            tier_name=first_tier,
            is_valid=False,
            confidence=0.0,
            reason=f"OCR failed: {str(e)[:150]}",
            language=state.original_job.get("payload", {}).get("options", {}).get("language", "en"),
            error={"code": "ocr_engine_error", "message": str(e)[:200]}
        )
        all_processed.append(result)

        # Check if more images
        image_count = state.original_job.get("payload", {}).get("image_count", 1)
        if next_image_index + 1 < image_count:
            dummy_state = PendingValidationState(
                original_job=state.original_job,
                image_index=next_image_index,
                tier_name=first_tier,
                ocr_text="",
                remaining_tiers=[],
                processed_results=all_processed,
                validation_job_id=f"val-{uuid.uuid4()}",
                created_at=datetime.utcnow().isoformat() + "Z"
            )
            await _process_next_image(dummy_state, result, next_image_index + 1)
        else:
            await _create_completion_and_send(state.original_job, all_processed)


async def process_validation_result(
    state: PendingValidationState,
    is_valid: bool,
    confidence: float,
    reason: str
) -> None:
    """
    Process the validation result and continue OCR workflow.

    This is the main entry point called after receiving a validation callback.

    Args:
        state: The pending validation state
        is_valid: Whether the OCR output was valid
        confidence: Confidence score (0.0-1.0)
        reason: Reason for validation result
    """
    logger.info(
        f"Processing validation result [job_id={state.original_job.get('job_id')}, "
        f"image_index={state.image_index}, tier={state.tier_name}, "
        f"is_valid={is_valid}, confidence={confidence}]"
    )

    language = state.original_job.get("payload", {}).get("options", {}).get("language", "en")
    image_count = state.original_job.get("payload", {}).get("image_count", 1)

    if is_valid:
        # OCR output is valid - create result and continue
        result = _build_image_result(
            image_index=state.image_index,
            ocr_text=state.ocr_text,
            tier_name=state.tier_name,
            is_valid=True,
            confidence=confidence,
            reason=reason,
            language=language
        )

        # Check if there are more images to process
        next_image_index = state.image_index + 1
        if next_image_index < image_count:
            # Process next image
            await _process_next_image(state, result, next_image_index)
        else:
            # All images done - send completion
            all_results = state.processed_results + [result]
            # Sort by index to ensure alignment
            all_results.sort(key=lambda r: r["index"])
            await _create_completion_and_send(state.original_job, all_results)

    else:
        # OCR output is invalid - try next tier or fail
        if state.remaining_tiers:
            # Try next tier
            next_tier = state.remaining_tiers[0]
            remaining = state.remaining_tiers[1:]
            await _process_with_next_tier(state, next_tier, remaining)
        else:
            # No more tiers - mark image as failed
            result = _build_image_result(
                image_index=state.image_index,
                ocr_text=state.ocr_text,
                tier_name=state.tier_name,
                is_valid=False,
                confidence=confidence,
                reason=reason,
                language=language,
                error={"code": "ocr_no_valid_output", "message": reason[:200]}
            )

            # Check if there are more images
            next_image_index = state.image_index + 1
            if next_image_index < image_count:
                # Process next image even though this one failed
                await _process_next_image(state, result, next_image_index)
            else:
                # All images done
                all_results = state.processed_results + [result]
                all_results.sort(key=lambda r: r["index"])
                await _create_completion_and_send(state.original_job, all_results)
