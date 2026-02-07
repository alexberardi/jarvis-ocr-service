"""Tests for app/queue_schemas.py - validate_ocr_request and create_completion_message."""

import copy

import pytest

from app.queue_schemas import (
    SchemaValidationError,
    create_completion_message,
    validate_ocr_request,
)


class TestValidateOcrRequest:
    """Tests for validate_ocr_request function."""

    def test_valid_message_passes(self, valid_queue_message):
        validate_ocr_request(valid_queue_message)  # Should not raise

    def test_missing_required_field(self, valid_queue_message):
        for field in ["schema_version", "job_id", "workflow_id", "job_type",
                       "source", "target", "created_at", "attempt",
                       "reply_to", "payload", "trace"]:
            msg = copy.deepcopy(valid_queue_message)
            del msg[field]
            with pytest.raises(SchemaValidationError, match=f"Missing required field: {field}"):
                validate_ocr_request(msg)

    def test_invalid_schema_version(self, valid_queue_message):
        msg = copy.deepcopy(valid_queue_message)
        msg["schema_version"] = 2
        with pytest.raises(SchemaValidationError, match="Invalid schema_version"):
            validate_ocr_request(msg)

    def test_invalid_job_type(self, valid_queue_message):
        msg = copy.deepcopy(valid_queue_message)
        msg["job_type"] = "ocr.wrong_type"
        with pytest.raises(SchemaValidationError, match="Invalid job_type"):
            validate_ocr_request(msg)

    def test_empty_reply_to(self, valid_queue_message):
        msg = copy.deepcopy(valid_queue_message)
        msg["reply_to"] = ""
        with pytest.raises(SchemaValidationError, match="reply_to must be a non-empty string"):
            validate_ocr_request(msg)

    def test_invalid_attempt_zero(self, valid_queue_message):
        msg = copy.deepcopy(valid_queue_message)
        msg["attempt"] = 0
        with pytest.raises(SchemaValidationError, match="attempt must be an integer >= 1"):
            validate_ocr_request(msg)

    def test_invalid_attempt_string(self, valid_queue_message):
        msg = copy.deepcopy(valid_queue_message)
        msg["attempt"] = "one"
        with pytest.raises(SchemaValidationError, match="attempt must be an integer"):
            validate_ocr_request(msg)

    def test_invalid_created_at_format(self, valid_queue_message):
        msg = copy.deepcopy(valid_queue_message)
        msg["created_at"] = "not-a-date"
        with pytest.raises(SchemaValidationError, match="Invalid created_at format"):
            validate_ocr_request(msg)

    def test_missing_image_refs(self, valid_queue_message):
        msg = copy.deepcopy(valid_queue_message)
        del msg["payload"]["image_refs"]
        with pytest.raises(SchemaValidationError, match="payload.image_refs is required"):
            validate_ocr_request(msg)

    def test_empty_image_refs(self, valid_queue_message):
        msg = copy.deepcopy(valid_queue_message)
        msg["payload"]["image_refs"] = []
        msg["payload"]["image_count"] = 0
        with pytest.raises(SchemaValidationError):
            validate_ocr_request(msg)

    def test_too_many_image_refs(self, valid_queue_message):
        msg = copy.deepcopy(valid_queue_message)
        msg["payload"]["image_refs"] = [
            {"kind": "s3", "value": f"s3://bucket/img{i}.png", "index": i}
            for i in range(9)
        ]
        msg["payload"]["image_count"] = 9
        with pytest.raises(SchemaValidationError, match="1-8 items"):
            validate_ocr_request(msg)

    def test_image_ref_missing_fields(self, valid_queue_message):
        msg = copy.deepcopy(valid_queue_message)
        msg["payload"]["image_refs"] = [{"kind": "s3"}]
        with pytest.raises(SchemaValidationError, match="must have 'kind', 'value', and 'index'"):
            validate_ocr_request(msg)

    def test_image_ref_invalid_kind(self, valid_queue_message):
        msg = copy.deepcopy(valid_queue_message)
        msg["payload"]["image_refs"] = [
            {"kind": "ftp", "value": "ftp://server/img.png", "index": 0}
        ]
        with pytest.raises(SchemaValidationError, match="Invalid image_refs"):
            validate_ocr_request(msg)

    def test_duplicate_index(self, valid_queue_message):
        msg = copy.deepcopy(valid_queue_message)
        msg["payload"]["image_refs"] = [
            {"kind": "s3", "value": "s3://bucket/a.png", "index": 0},
            {"kind": "s3", "value": "s3://bucket/b.png", "index": 0},
        ]
        msg["payload"]["image_count"] = 2
        with pytest.raises(SchemaValidationError, match="Duplicate index"):
            validate_ocr_request(msg)

    def test_image_count_mismatch(self, valid_queue_message):
        msg = copy.deepcopy(valid_queue_message)
        msg["payload"]["image_count"] = 5
        with pytest.raises(SchemaValidationError, match="must match image_count"):
            validate_ocr_request(msg)

    def test_image_count_derived_when_missing(self, valid_queue_message):
        msg = copy.deepcopy(valid_queue_message)
        del msg["payload"]["image_count"]
        validate_ocr_request(msg)  # Should not raise
        assert msg["payload"]["image_count"] == 1

    def test_invalid_options_type(self, valid_queue_message):
        msg = copy.deepcopy(valid_queue_message)
        msg["payload"]["options"] = "not-a-dict"
        with pytest.raises(SchemaValidationError, match="payload.options must be an object"):
            validate_ocr_request(msg)

    def test_invalid_options_language(self, valid_queue_message):
        msg = copy.deepcopy(valid_queue_message)
        msg["payload"]["options"] = {"language": ""}
        with pytest.raises(SchemaValidationError, match="language must be a non-empty string"):
            validate_ocr_request(msg)

    def test_trace_missing_fields(self, valid_queue_message):
        msg = copy.deepcopy(valid_queue_message)
        msg["trace"] = {"request_id": "r1"}
        with pytest.raises(SchemaValidationError, match="trace must have"):
            validate_ocr_request(msg)

    def test_trace_not_dict(self, valid_queue_message):
        msg = copy.deepcopy(valid_queue_message)
        msg["trace"] = "not-a-dict"
        with pytest.raises(SchemaValidationError, match="trace must be an object"):
            validate_ocr_request(msg)


class TestCreateCompletionMessage:
    """Tests for create_completion_message function."""

    def test_success_status_with_valid_result(self, valid_queue_message):
        results = [
            {
                "index": 0,
                "ocr_text": "Hello",
                "truncated": False,
                "meta": {"is_valid": True, "confidence": 0.95, "tier": "tesseract"},
            }
        ]
        msg = create_completion_message(valid_queue_message, results)
        assert msg["payload"]["status"] == "success"
        assert msg["job_type"] == "ocr.completed"
        assert msg["schema_version"] == 1
        assert msg["source"] == "jarvis-ocr-service"

    def test_failed_status_when_no_valid_results(self, valid_queue_message):
        results = [
            {
                "index": 0,
                "ocr_text": "",
                "truncated": False,
                "meta": {"is_valid": False, "confidence": 0.0},
            }
        ]
        msg = create_completion_message(valid_queue_message, results)
        assert msg["payload"]["status"] == "failed"

    def test_failed_status_with_empty_results(self, valid_queue_message):
        msg = create_completion_message(valid_queue_message, [], error={"message": "boom", "code": "internal"})
        assert msg["payload"]["status"] == "failed"
        assert msg["payload"]["error"]["message"] == "boom"

    def test_workflow_id_preserved(self, valid_queue_message):
        msg = create_completion_message(valid_queue_message, [])
        assert msg["workflow_id"] == valid_queue_message["workflow_id"]

    def test_trace_preserved(self, valid_queue_message):
        msg = create_completion_message(valid_queue_message, [])
        assert msg["trace"]["request_id"] == "req-001"
        assert msg["trace"]["parent_job_id"] == "job-001"

    def test_target_set_to_source(self, valid_queue_message):
        msg = create_completion_message(valid_queue_message, [])
        assert msg["target"] == valid_queue_message["source"]

    def test_no_error_field_on_success(self, valid_queue_message):
        results = [{"index": 0, "ocr_text": "OK", "meta": {"is_valid": True}}]
        msg = create_completion_message(valid_queue_message, results)
        # Error should be {message: None, code: None} on success
        assert msg["payload"]["error"]["message"] is None
