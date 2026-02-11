"""Tests for validation state management."""

import json
import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime

from app.validation_state import PendingValidationState, ValidationStateManager


class TestPendingValidationState:
    """Test the state dataclass/model."""

    def test_create_state_with_all_required_fields(self):
        """State should require original_job, image_index, tier_name, ocr_text."""
        state = PendingValidationState(
            original_job={
                "job_id": "ocr-123",
                "workflow_id": "wf-456",
                "reply_to": "jarvis.recipes.jobs"
            },
            image_index=0,
            tier_name="tesseract",
            ocr_text="Spicy Beef Rice Bowls\n1 cup rice...",
            remaining_tiers=["apple_vision", "llm_local"],
            processed_results=[],
            validation_job_id="val-789",
            created_at="2026-02-03T12:00:00Z"
        )
        assert state.original_job["job_id"] == "ocr-123"
        assert state.tier_name == "tesseract"
        assert state.image_index == 0
        assert state.ocr_text == "Spicy Beef Rice Bowls\n1 cup rice..."
        assert state.remaining_tiers == ["apple_vision", "llm_local"]
        assert state.validation_job_id == "val-789"

    def test_serialize_to_json(self):
        """State should serialize to JSON for Redis storage."""
        state = PendingValidationState(
            original_job={
                "job_id": "ocr-123",
                "workflow_id": "wf-456",
                "reply_to": "jarvis.recipes.jobs"
            },
            image_index=0,
            tier_name="tesseract",
            ocr_text="Recipe text here",
            remaining_tiers=["apple_vision"],
            processed_results=[],
            validation_job_id="val-789",
            created_at="2026-02-03T12:00:00Z"
        )
        json_str = state.to_json()
        assert isinstance(json_str, str)
        assert "ocr-123" in json_str
        assert "tesseract" in json_str

    def test_deserialize_from_json(self):
        """State should deserialize from JSON."""
        json_str = json.dumps({
            "original_job": {"job_id": "ocr-123", "workflow_id": "wf-456"},
            "image_index": 0,
            "tier_name": "tesseract",
            "ocr_text": "Test text",
            "remaining_tiers": ["apple_vision"],
            "processed_results": [],
            "validation_job_id": "val-789",
            "created_at": "2026-02-03T12:00:00Z"
        })
        state = PendingValidationState.from_json(json_str)
        assert state.original_job["job_id"] == "ocr-123"
        assert state.tier_name == "tesseract"
        assert state.validation_job_id == "val-789"

    def test_roundtrip_preserves_all_fields(self):
        """Serialize then deserialize should preserve all data."""
        original = PendingValidationState(
            original_job={
                "job_id": "ocr-123",
                "workflow_id": "wf-456",
                "reply_to": "jarvis.recipes.jobs",
                "payload": {"image_refs": [{"index": 0}]}
            },
            image_index=2,
            tier_name="apple_vision",
            ocr_text="Full recipe text with\nmultiple lines",
            remaining_tiers=["llm_local", "llm_cloud"],
            processed_results=[{"index": 0, "ocr_text": "result 0"}],
            validation_job_id="val-abc-123",
            created_at="2026-02-03T15:30:00Z"
        )
        restored = PendingValidationState.from_json(original.to_json())
        assert original.original_job == restored.original_job
        assert original.image_index == restored.image_index
        assert original.tier_name == restored.tier_name
        assert original.ocr_text == restored.ocr_text
        assert original.remaining_tiers == restored.remaining_tiers
        assert original.processed_results == restored.processed_results
        assert original.validation_job_id == restored.validation_job_id
        assert original.created_at == restored.created_at

    def test_deserialize_handles_bytes(self):
        """State should deserialize from bytes (as returned from Redis)."""
        json_bytes = json.dumps({
            "original_job": {"job_id": "ocr-123"},
            "image_index": 0,
            "tier_name": "tesseract",
            "ocr_text": "Test",
            "remaining_tiers": [],
            "processed_results": [],
            "validation_job_id": "val-123",
            "created_at": "2026-02-03T12:00:00Z"
        }).encode('utf-8')
        state = PendingValidationState.from_json(json_bytes)
        assert state.original_job["job_id"] == "ocr-123"


class TestValidationStateManager:
    """Test Redis state storage operations."""

    @pytest.fixture
    def mock_redis(self):
        """Mock Redis client."""
        return MagicMock()

    @pytest.fixture
    def manager(self, mock_redis):
        """Create manager with mocked Redis."""
        return ValidationStateManager(redis_client=mock_redis)

    @pytest.fixture
    def sample_state(self):
        """Sample state for testing."""
        return PendingValidationState(
            original_job={
                "job_id": "ocr-123",
                "workflow_id": "wf-456",
                "reply_to": "jarvis.recipes.jobs"
            },
            image_index=0,
            tier_name="tesseract",
            ocr_text="Test OCR text",
            remaining_tiers=["apple_vision"],
            processed_results=[],
            validation_job_id="val-123",
            created_at="2026-02-03T12:00:00Z"
        )

    def test_save_state_stores_in_redis_with_correct_key(self, manager, mock_redis, sample_state):
        """save() should store JSON at key 'ocr:pending_validation:<job_id>'."""
        manager.save(sample_state)

        mock_redis.setex.assert_called_once()
        call_args = mock_redis.setex.call_args
        assert call_args[0][0] == "ocr:pending_validation:val-123"
        assert call_args[0][1] == 300  # Default TTL

    def test_save_state_uses_configured_ttl(self, mock_redis):
        """TTL should come from config."""
        manager = ValidationStateManager(redis_client=mock_redis, ttl=600)
        state = PendingValidationState(
            original_job={"job_id": "ocr-123"},
            image_index=0,
            tier_name="tesseract",
            ocr_text="Test",
            remaining_tiers=[],
            processed_results=[],
            validation_job_id="val-123",
            created_at="2026-02-03T12:00:00Z"
        )
        manager.save(state)

        call_args = mock_redis.setex.call_args
        assert call_args[0][1] == 600

    def test_save_state_stores_valid_json(self, manager, mock_redis, sample_state):
        """save() should store valid JSON that can be deserialized."""
        manager.save(sample_state)

        call_args = mock_redis.setex.call_args
        stored_json = call_args[0][2]
        # Should be valid JSON
        parsed = json.loads(stored_json)
        assert parsed["validation_job_id"] == "val-123"
        assert parsed["tier_name"] == "tesseract"

    def test_get_state_returns_deserialized_state(self, manager, mock_redis):
        """get() should return PendingValidationState from Redis."""
        mock_redis.get.return_value = json.dumps({
            "original_job": {"job_id": "ocr-123"},
            "image_index": 0,
            "tier_name": "tesseract",
            "ocr_text": "Test",
            "remaining_tiers": [],
            "processed_results": [],
            "validation_job_id": "val-123",
            "created_at": "2026-02-03T12:00:00Z"
        }).encode('utf-8')

        state = manager.get("val-123")

        mock_redis.get.assert_called_with("ocr:pending_validation:val-123")
        assert state is not None
        assert state.validation_job_id == "val-123"

    def test_get_nonexistent_state_returns_none(self, manager, mock_redis):
        """get() should return None if key doesn't exist."""
        mock_redis.get.return_value = None

        state = manager.get("nonexistent")

        assert state is None

    def test_delete_state_removes_from_redis(self, manager, mock_redis):
        """delete() should remove key from Redis."""
        manager.delete("val-123")

        mock_redis.delete.assert_called_with("ocr:pending_validation:val-123")

    def test_get_handles_corrupted_json(self, manager, mock_redis):
        """get() should return None and log error for invalid JSON."""
        mock_redis.get.return_value = b'not valid json'

        state = manager.get("val-123")

        assert state is None

    def test_get_handles_string_response(self, manager, mock_redis):
        """get() should handle string response from Redis."""
        mock_redis.get.return_value = json.dumps({
            "original_job": {"job_id": "ocr-123"},
            "image_index": 0,
            "tier_name": "tesseract",
            "ocr_text": "Test",
            "remaining_tiers": [],
            "processed_results": [],
            "validation_job_id": "val-123",
            "created_at": "2026-02-03T12:00:00Z"
        })  # String, not bytes

        state = manager.get("val-123")

        assert state is not None
        assert state.validation_job_id == "val-123"

    def test_key_prefix_is_correct(self, manager):
        """Manager should use correct key prefix."""
        assert manager.key_prefix == "ocr:pending_validation:"
