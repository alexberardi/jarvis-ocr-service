"""JSON schema validators for queue messages."""

import json
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime

logger = logging.getLogger(__name__)


class SchemaValidationError(Exception):
    """Raised when a message fails schema validation."""
    pass


def validate_ocr_request(message: Dict[str, Any]) -> None:
    """
    Validate an OCR request message against the v1 schema.
    
    Raises:
        SchemaValidationError: If validation fails
    """
    # Required top-level fields
    required_fields = [
        "schema_version", "job_id", "workflow_id", "job_type",
        "source", "target", "created_at", "attempt", "reply_to", "payload", "trace"
    ]
    
    for field in required_fields:
        if field not in message:
            raise SchemaValidationError(f"Missing required field: {field}")
    
    # Validate schema_version
    if message["schema_version"] != 1:
        raise SchemaValidationError(f"Invalid schema_version: {message['schema_version']}, expected 1")
    
    # Validate job_type
    if message["job_type"] != "ocr.extract_text.requested":
        raise SchemaValidationError(f"Invalid job_type: {message['job_type']}, expected 'ocr.extract_text.requested'")
    
    # Validate reply_to
    if not message["reply_to"] or not isinstance(message["reply_to"], str) or len(message["reply_to"]) < 1:
        raise SchemaValidationError("reply_to must be a non-empty string")
    
    # Validate attempt
    if not isinstance(message["attempt"], int) or message["attempt"] < 1:
        raise SchemaValidationError("attempt must be an integer >= 1")
    
    # Validate created_at (ISO-8601)
    try:
        datetime.fromisoformat(message["created_at"].replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        raise SchemaValidationError(f"Invalid created_at format: {message['created_at']}")
    
    # Validate payload
    payload = message["payload"]
    if not isinstance(payload, dict):
        raise SchemaValidationError("payload must be an object")
    
    # Validate image_refs array
    if "image_refs" not in payload:
        raise SchemaValidationError("payload.image_refs is required")
    
    image_refs = payload["image_refs"]
    if not isinstance(image_refs, list):
        raise SchemaValidationError("payload.image_refs must be an array")
    
    if len(image_refs) < 1 or len(image_refs) > 8:
        raise SchemaValidationError("payload.image_refs must have 1-8 items")
    
    # image_count is optional - derive from image_refs if not provided
    # If provided, validate it matches the array length
    if "image_count" in payload:
        image_count = payload["image_count"]
        if not isinstance(image_count, int) or image_count < 1 or image_count > 8:
            raise SchemaValidationError("payload.image_count must be an integer between 1 and 8")
        
        if len(image_refs) != image_count:
            raise SchemaValidationError(f"payload.image_refs length ({len(image_refs)}) must match image_count ({image_count})")
    else:
        # Backward compatibility: derive image_count from array length
        payload["image_count"] = len(image_refs)
    
    # Validate each image_ref
    seen_indices = set()
    for i, image_ref in enumerate(image_refs):
        if not isinstance(image_ref, dict):
            raise SchemaValidationError(f"payload.image_refs[{i}] must be an object")
        
        if "kind" not in image_ref or "value" not in image_ref or "index" not in image_ref:
            raise SchemaValidationError(f"payload.image_refs[{i}] must have 'kind', 'value', and 'index' fields")
        
        if image_ref["kind"] not in ["local_path", "s3", "minio", "db"]:
            raise SchemaValidationError(f"Invalid image_refs[{i}].kind: {image_ref['kind']}")
        
        if not isinstance(image_ref["value"], str) or len(image_ref["value"]) < 1:
            raise SchemaValidationError(f"payload.image_refs[{i}].value must be a non-empty string")
        
        index = image_ref["index"]
        if not isinstance(index, int) or index < 0:
            raise SchemaValidationError(f"payload.image_refs[{i}].index must be a non-negative integer")
        
        if index in seen_indices:
            raise SchemaValidationError(f"Duplicate index {index} in image_refs")
        seen_indices.add(index)
    
    # Validate options if present
    if "options" in payload:
        if not isinstance(payload["options"], dict):
            raise SchemaValidationError("payload.options must be an object")
        if "language" in payload["options"]:
            if not isinstance(payload["options"]["language"], str) or len(payload["options"]["language"]) < 1:
                raise SchemaValidationError("payload.options.language must be a non-empty string")
    
    # Validate trace
    trace = message["trace"]
    if not isinstance(trace, dict):
        raise SchemaValidationError("trace must be an object")
    
    if "request_id" not in trace or "parent_job_id" not in trace:
        raise SchemaValidationError("trace must have 'request_id' and 'parent_job_id' fields")


def create_completion_message(
    original_message: Dict[str, Any],
    results: List[Dict[str, Any]],
    error: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Create an ocr.completed message from an original request.
    
    Args:
        original_message: The original OCR request message
        results: List of result dicts, each with index, ocr_text, truncated, meta
        error: Optional top-level error dict (only for job-level failures)
    
    Returns:
        Completion message dict
    """
    # Determine status: success if at least one image has is_valid=true
    # If results is empty (job-level failure), status is failed
    status = "failed"
    if results:
        for result in results:
            if result.get("meta", {}).get("is_valid", False):
                status = "success"
                break
    
    # Generate new job_id for completion event
    import uuid
    completion_job_id = str(uuid.uuid4())
    
    return {
        "schema_version": 1,
        "job_id": completion_job_id,
        "workflow_id": original_message["workflow_id"],
        "job_type": "ocr.completed",
        "source": "jarvis-ocr-service",
        "target": original_message["source"],
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
            "request_id": original_message["trace"].get("request_id"),
            "parent_job_id": original_message["job_id"]
        }
    }

