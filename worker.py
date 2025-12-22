#!/usr/bin/env python3
"""Worker script to process OCR jobs from Redis queue per queue-flow.md PRD."""

import asyncio
import base64
import json
import logging
import sys
import time
from datetime import datetime
from typing import Optional, Dict, Any, List

from app.config import config
from app.provider_manager import ProviderManager
from app.queue_client import queue_client
from app.queue_schemas import validate_ocr_request, create_completion_message, SchemaValidationError
from app.image_resolver import resolve_image, ImageResolverError
from app.text_utils import normalize_text, truncate_text
from app.tier_mapping import get_tier_order, provider_to_tier, tier_to_provider
from app.exceptions import OCRProcessingException, ProviderUnavailableException

# Configure logging
logging.basicConfig(
    level=getattr(logging, config.OCR_LOG_LEVEL),
    format='{"timestamp": "%(asctime)s", "level": "%(levelname)s", "name": "%(name)s", "message": "%(message)s"}',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


def should_retry(error_code: str, attempt: int) -> bool:
    """
    Determine if a job should be retried.
    
    Args:
        error_code: Error code from failure
        attempt: Current attempt number
    
    Returns:
        True if should retry, False otherwise
    """
    # Don't retry if max attempts reached
    if attempt >= config.OCR_MAX_ATTEMPTS:
        return False
    
    # Don't retry on non-retryable errors
    non_retryable = ["bad_request", "image_not_found", "schema_invalid", "unsupported_media"]
    if error_code in non_retryable:
        return False
    
    # Retry on transient errors
    retryable = ["ocr_engine_error", "file_read_error", "redis_error", "internal_error"]
    return error_code in retryable


async def process_single_image_with_tiers(
    image_ref: Dict[str, Any],
    image_index: int,
    provider_manager: ProviderManager,
    enabled_tiers: List[str],
    language: str
) -> Dict[str, Any]:
    """
    Process a single image through tiered pipeline with short-circuiting.
    
    Args:
        image_ref: Image reference dict with kind, value, index
        image_index: Index of the image
        provider_manager: Provider manager instance
        enabled_tiers: List of enabled tier names
        language: Language hint
    
    Returns:
        Result dict with index, ocr_text, truncated, meta
    """
    tier_order = get_tier_order(enabled_tiers)
    
    # Try to resolve image first
    try:
        image_bytes, content_type = resolve_image(image_ref)
    except ImageResolverError as e:
        error_msg = str(e)
        # Check if it's a PDF rejection
        if "unsupported_media" in error_msg or image_ref["value"].lower().endswith('.pdf'):
            logger.warning(f"PDF detected for image [index={image_index}]: {error_msg}")
            return {
                "index": image_index,
                "ocr_text": "",
                "truncated": False,
                "meta": {
                    "language": language,
                    "confidence": 0.0,
                    "text_len": 0,
                    "is_valid": False,
                    "tier": "unknown",
                    "validation_reason": "PDF files are not supported in v1"
                },
                "error": {
                    "code": "unsupported_media",
                    "message": "PDF files are not supported in v1"
                }
            }
        else:
            # Other image resolution errors
            logger.warning(f"Failed to resolve image [index={image_index}]: {error_msg}")
            return {
                "index": image_index,
                "ocr_text": "",
                "truncated": False,
                "meta": {
                    "language": language,
                    "confidence": 0.0,
                    "text_len": 0,
                    "is_valid": False,
                    "tier": "unknown",
                    "validation_reason": error_msg[:200]
                },
                "error": {
                    "code": "image_not_found",
                    "message": error_msg[:200]
                }
            }
    
    # Double-check for PDF (should be caught by resolver, but safety check)
    if content_type == "application/pdf" or image_ref["value"].lower().endswith('.pdf'):
        logger.warning(f"PDF detected for image [index={image_index}]")
        return {
            "index": image_index,
            "ocr_text": "",
            "truncated": False,
            "meta": {
                "language": language,
                "confidence": 0.0,
                "text_len": 0,
                "is_valid": False,
                "tier": "unknown",
                "validation_reason": "PDF files are not supported in v1"
            },
            "error": {
                "code": "unsupported_media",
                "message": "PDF files are not supported in v1"
            }
        }
    
    # Convert to base64 for provider_manager
    image_base64 = base64.b64encode(image_bytes).decode('utf-8')
    language_hints = [language] if language else None
    
    # Try each tier in order until we get valid output
    last_tier = None
    last_error = None
    
    for tier_name in tier_order:
        try:
            provider_name = tier_to_provider(tier_name)
            
            # Check if provider is available
            if provider_name not in provider_manager.providers:
                continue
            
            provider = provider_manager.providers[provider_name]
            if not provider.is_available():
                continue
            
            logger.debug(f"Trying tier {tier_name} for image {image_index}")
            
            # Process with this provider
            result, provider_used = await provider_manager.process_image(
                image_base64=image_base64,
                provider_name=provider_name,
                language_hints=language_hints,
                return_boxes=False,  # Don't need boxes for queue flow
                mode="document"
            )
            
            # Normalize text
            ocr_text = normalize_text(result.text)
            
            # Validate with LLM
            is_valid, confidence, reason = await provider_manager._validate_ocr_with_llm(ocr_text)
            
            # Check optional minimum confidence if configured
            if config.OCR_MIN_CONFIDENCE is not None and confidence < config.OCR_MIN_CONFIDENCE:
                logger.debug(f"Tier {tier_name} failed confidence threshold: {confidence} < {config.OCR_MIN_CONFIDENCE}")
                last_tier = tier_name
                last_error = f"Confidence {confidence:.2f} below threshold {config.OCR_MIN_CONFIDENCE}"
                continue
            
            # If valid, accept this tier and short-circuit
            if is_valid:
                # Truncate text if needed
                truncated_text, was_truncated = truncate_text(ocr_text, config.OCR_MAX_TEXT_BYTES)
                
                # Use OCR provider confidence if available, otherwise use LLM confidence
                # For now, use LLM confidence (providers don't expose confidence in a standardized way)
                final_confidence = confidence
                
                logger.info(
                    f"Image {image_index} processed successfully with tier {tier_name} "
                    f"[is_valid={is_valid}, confidence={final_confidence:.2f}, "
                    f"text_len={len(truncated_text.encode('utf-8'))}, truncated={was_truncated}]"
                )
                
                result = {
                    "index": image_index,
                    "ocr_text": truncated_text,
                    "truncated": was_truncated,
                    "meta": {
                        "language": language,
                        "confidence": final_confidence,
                        "text_len": len(truncated_text.encode("utf-8")),
                        "is_valid": True,
                        "tier": tier_name,
                        "validation_reason": reason[:200] if reason else None
                    },
                    "error": None  # No error for successful results
                }
                
                # Log validation reason at INFO level for success
                logger.info(
                    f"Image {image_index} validated successfully with tier {tier_name} "
                    f"[reason: {reason[:200] if reason else 'N/A'}]"
                )
                
                return result
            else:
                logger.debug(f"Tier {tier_name} produced invalid output: {reason}")
                last_tier = tier_name
                last_error = reason[:200] if reason else "Invalid output"
                continue
                
        except (ProviderUnavailableException, OCRProcessingException, ValueError) as e:
            logger.debug(f"Tier {tier_name} failed for image {image_index}: {e}")
            last_tier = tier_name
            last_error = str(e)[:200]
            continue
        except Exception as e:
            logger.warning(f"Unexpected error with tier {tier_name} for image {image_index}: {e}")
            last_tier = tier_name
            last_error = f"Tier error: {str(e)[:200]}"
            continue
    
    # All tiers failed
    validation_reason = last_error or "All tiers failed validation"
    logger.warning(
        f"All tiers failed for image {image_index} "
        f"[last_tier={last_tier}, reason: {validation_reason[:200]}]"
    )
    
    return {
        "index": image_index,
        "ocr_text": "",
        "truncated": False,
        "meta": {
            "language": language,
            "confidence": 0.0,
            "text_len": 0,
            "is_valid": False,
            "tier": last_tier or "unknown",
            "validation_reason": validation_reason[:200]
        },
        "error": {
            "code": "ocr_no_valid_output",
            "message": validation_reason[:200]
        }
    }


async def process_ocr_job(message: Dict[str, Any], provider_manager: ProviderManager) -> Dict[str, Any]:
    """
    Process an OCR job with multiple images according to queue-flow.md PRD.
    
    Args:
        message: OCR request message (validated)
        provider_manager: Provider manager instance
    
    Returns:
        Completion message dict
    """
    job_id = message["job_id"]
    workflow_id = message["workflow_id"]
    attempt = message["attempt"]
    start_time = time.time()
    
    image_refs = message["payload"]["image_refs"]
    image_count = message["payload"]["image_count"]
    language = message["payload"].get("options", {}).get("language", config.OCR_LANGUAGE_DEFAULT)
    
    logger.info(
        f"Processing OCR job [job_id={job_id}, workflow_id={workflow_id}, "
        f"attempt={attempt}, images={image_count}]"
    )
    
    # Get enabled tiers
    enabled_tiers = config.get_enabled_tiers()
    
    # Process each image
    results = []
    for image_ref in image_refs:
        image_index = image_ref["index"]
        result = await process_single_image_with_tiers(
            image_ref=image_ref,
            image_index=image_index,
            provider_manager=provider_manager,
            enabled_tiers=enabled_tiers,
            language=language
        )
        results.append(result)
    
    # Sort results by index to ensure alignment
    results.sort(key=lambda r: r["index"])
    
    # Create completion message
    duration_ms = (time.time() - start_time) * 1000
    
    # Determine if any image succeeded
    any_valid = any(r["meta"]["is_valid"] for r in results)
    
    logger.info(
        f"OCR job completed [job_id={job_id}, workflow_id={workflow_id}, "
        f"valid_images={sum(1 for r in results if r['meta']['is_valid'])}/{image_count}, "
        f"duration_ms={duration_ms:.2f}]"
    )
    
    completion_message = create_completion_message(
        original_message=message,
        results=results,
        error=None  # Individual image errors are in results, top-level error only for job failures
    )
    
    return completion_message


async def process_job_with_retry(
    message: Dict[str, Any],
    provider_manager: ProviderManager
) -> None:
    """
    Process a job with validation, retry logic, and completion message emission.
    
    Args:
        message: Message dict from queue (already parsed)
        provider_manager: Provider manager instance
    """
    try:
        # Validate schema
        try:
            validate_ocr_request(message)
        except SchemaValidationError as e:
            logger.error(f"Schema validation failed: {e}")
            # Emit failure message if we have reply_to
            if "reply_to" in message and message["reply_to"]:
                error_message = create_completion_message(
                    original_message=message,
                    results=[],  # Empty results for schema error
                    error={"message": str(e), "code": "bad_request"}
                )
                queue_client.enqueue(message["reply_to"], error_message)
            return  # Don't retry schema errors
        
        job_id = message["job_id"]
        attempt = message["attempt"]
        reply_to = message.get("reply_to")
        
        # Process job
        try:
            completion_message = await process_ocr_job(message, provider_manager)
        except Exception as e:
            # Job-level failure (e.g., Redis outage, worker crash)
            logger.error(f"Job-level failure [job_id={job_id}]: {e}", exc_info=True)
            completion_message = create_completion_message(
                original_message=message,
                results=[],  # Empty results for job failure
                error={"message": str(e)[:200], "code": "internal_error"}
            )
        
        # Emit completion message to reply_to queue
        if reply_to:
            success = queue_client.enqueue(reply_to, completion_message)
            if not success:
                logger.error(f"Failed to enqueue completion message to {reply_to} [job_id={job_id}]")
                # Retry logic could go here if needed
        else:
            logger.warning(f"No reply_to queue specified [job_id={job_id}], completion message not sent")
        
        # Check if we should retry on failure
        if completion_message["payload"]["status"] == "failed":
            error_code = completion_message["payload"]["error"]["code"]
            if should_retry(error_code, attempt):
                # Increment attempt and re-queue to BACK of queue (RPUSH)
                message["attempt"] = attempt + 1
                queue_client.enqueue(queue_client.queue_name, message, to_back=True)
                logger.info(f"Re-queued job for retry [job_id={job_id}, attempt={attempt + 1}]")
        
    except Exception as e:
        logger.error(f"Error in process_job_with_retry: {e}", exc_info=True)


async def worker_loop(provider_manager: ProviderManager, timeout: int = 5):
    """Main worker loop - continuously pull and process jobs."""
    logger.info(f"Worker started - listening on queue: {queue_client.queue_name}")
    
    while True:
        try:
            # Dequeue job (blocking with timeout)
            job_data = queue_client.dequeue_job(timeout)
            
            if job_data is None:
                # No jobs available, continue waiting
                continue
            
            # Process the job (handles retries internally)
            # job_data is already a dict from dequeue_job
            await process_job_with_retry(job_data, provider_manager)
            
        except KeyboardInterrupt:
            logger.info("Worker shutting down...")
            break
        except Exception as e:
            logger.error(f"Error in worker loop: {e}", exc_info=True)
            # Continue processing other jobs
            await asyncio.sleep(1)


async def main():
    """Main entry point."""
    logger.info("Starting OCR Worker (queue-flow v1)...")
    
    # Initialize provider manager
    try:
        provider_manager = ProviderManager()
        logger.info("Provider manager initialized")
    except Exception as e:
        logger.error(f"Failed to initialize provider manager: {e}")
        sys.exit(1)
    
    # Check Redis connection
    status = queue_client.get_status()
    if not status.get("redis_connected"):
        logger.error("Redis not available - cannot process jobs")
        sys.exit(1)
    
    logger.info(f"Connected to Redis queue: {queue_client.queue_name}")
    logger.info(f"Configuration: max_text_bytes={config.OCR_MAX_TEXT_BYTES}, max_attempts={config.OCR_MAX_ATTEMPTS}")
    logger.info(f"Enabled tiers: {config.get_enabled_tiers()}")
    
    # Start worker loop
    try:
        await worker_loop(provider_manager)
    except KeyboardInterrupt:
        logger.info("Worker stopped")


if __name__ == "__main__":
    asyncio.run(main())
