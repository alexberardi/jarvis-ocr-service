"""Integration tests for the full async validation flow."""

import json
import pytest
from unittest.mock import MagicMock, patch, AsyncMock

from app.validation_state import PendingValidationState, ValidationStateManager
from app.validation_callback import ValidationCallbackPayload, validation_callback
from app.continue_processing import process_validation_result, _create_completion_and_send
from app.llm_queue_client import LLMQueueClient


class TestAsyncValidationFlowIntegration:
    """Integration tests for full async validation flow."""

    @pytest.fixture
    def mock_redis(self):
        """Mock Redis client with working storage."""
        storage = {}

        def mock_get(key):
            return storage.get(key)

        def mock_setex(key, ttl, value):
            storage[key] = value.encode('utf-8') if isinstance(value, str) else value

        def mock_delete(key):
            storage.pop(key, None)

        mock = MagicMock()
        mock.get = MagicMock(side_effect=mock_get)
        mock.setex = MagicMock(side_effect=mock_setex)
        mock.delete = MagicMock(side_effect=mock_delete)
        mock._storage = storage  # Expose for test inspection
        return mock

    @pytest.fixture
    def state_manager(self, mock_redis):
        """Create state manager with mock Redis."""
        return ValidationStateManager(redis_client=mock_redis, ttl=300)

    @pytest.fixture
    def sample_ocr_job(self):
        """Sample OCR job from recipes service."""
        return {
            "schema_version": 1,
            "job_id": "ocr-job-123",
            "workflow_id": "wf-456",
            "job_type": "ocr.extract_text.requested",
            "source": "jarvis-recipes-server",
            "target": "jarvis-ocr-service",
            "created_at": "2026-02-03T12:00:00Z",
            "attempt": 1,
            "reply_to": "jarvis.recipes.jobs",
            "payload": {
                "image_refs": [
                    {"index": 0, "kind": "local_path", "value": "/path/to/recipe.jpg"}
                ],
                "image_count": 1,
                "options": {"language": "en"}
            },
            "trace": {
                "request_id": "req-789",
                "parent_job_id": "parent-123"
            }
        }

    @pytest.mark.asyncio
    async def test_full_flow_single_image_valid(self, state_manager, sample_ocr_job):
        """
        Test complete flow: OCR -> enqueue validation -> callback -> completion.

        Scenario:
        1. OCR extracts text from image
        2. State is saved to Redis
        3. Validation job is enqueued to LLM proxy
        4. LLM callback received with valid result
        5. Completion message sent to recipes queue
        """
        # Step 1: Create pending validation state (simulating OCR completion)
        ocr_text = "Spicy Beef Rice Bowls\n\nIngredients:\n- 1 lb ground beef\n- 2 cups rice"
        state = PendingValidationState(
            original_job=sample_ocr_job,
            image_index=0,
            tier_name="tesseract",
            ocr_text=ocr_text,
            remaining_tiers=["apple_vision"],
            processed_results=[],
            validation_job_id="val-001",
            created_at="2026-02-03T12:00:00Z"
        )

        # Step 2: Save state to Redis
        state_manager.save(state)

        # Verify state was saved
        loaded_state = state_manager.get("val-001")
        assert loaded_state is not None
        assert loaded_state.ocr_text == ocr_text

        # Step 3: Simulate LLM callback with valid result
        callback_payload = ValidationCallbackPayload(
            job_id="llm-job-001",
            status="succeeded",
            result={"content": json.dumps({
                "is_valid": True,
                "confidence": 0.95,
                "reason": "Clear recipe text with ingredients list"
            })},
            metadata={
                "validation_state_key": "val-001",
                "ocr_job_id": "ocr-job-123",
                "workflow_id": "wf-456",
                "image_index": 0,
                "tier_name": "tesseract"
            }
        )

        # Step 4: Process callback
        with patch('app.validation_callback.get_state_manager', return_value=state_manager), \
             patch('app.continue_processing.queue_client') as mock_queue:
            mock_queue.enqueue.return_value = True

            result = await validation_callback(callback_payload)

            # Verify callback succeeded
            assert result["status"] == "ok"
            assert result["processed"] is True

            # Verify completion message was sent
            mock_queue.enqueue.assert_called_once()
            queue_name = mock_queue.enqueue.call_args[0][0]
            message = mock_queue.enqueue.call_args[0][1]

            assert queue_name == "jarvis.recipes.jobs"
            assert message["job_type"] == "ocr.completed"
            assert message["payload"]["status"] == "success"
            assert len(message["payload"]["results"]) == 1
            assert message["payload"]["results"][0]["meta"]["is_valid"] is True

        # Verify state was deleted
        assert state_manager.get("val-001") is None

    @pytest.mark.asyncio
    async def test_full_flow_validation_fails_tries_next_tier(self, state_manager, sample_ocr_job):
        """
        Test flow where first tier fails validation and next tier is tried.

        Scenario:
        1. Tesseract produces garbled text
        2. Validation fails
        3. Apple Vision tier is tried
        4. (Simulated) Apple Vision succeeds
        """
        # First tier (tesseract) produces garbled output
        state = PendingValidationState(
            original_job=sample_ocr_job,
            image_index=0,
            tier_name="tesseract",
            ocr_text="asdkjh asd8923 jkasdf",  # Garbled
            remaining_tiers=["apple_vision", "llm_local"],
            processed_results=[],
            validation_job_id="val-002",
            created_at="2026-02-03T12:00:00Z"
        )
        state_manager.save(state)

        # Callback with invalid result
        callback_payload = ValidationCallbackPayload(
            job_id="llm-job-002",
            status="succeeded",
            result={"content": json.dumps({
                "is_valid": False,
                "confidence": 0.15,
                "reason": "Text appears to be garbled nonsense"
            })},
            metadata={
                "validation_state_key": "val-002",
                "ocr_job_id": "ocr-job-123",
                "workflow_id": "wf-456",
                "image_index": 0,
                "tier_name": "tesseract"
            }
        )

        # Process callback - should try next tier
        with patch('app.validation_callback.get_state_manager', return_value=state_manager), \
             patch('app.continue_processing._process_with_next_tier', new_callable=AsyncMock) as mock_next_tier:

            await validation_callback(callback_payload)

            # Verify next tier was called
            mock_next_tier.assert_called_once()
            call_args = mock_next_tier.call_args[0]
            assert call_args[1] == "apple_vision"  # next_tier
            assert call_args[2] == ["llm_local"]  # remaining_tiers

    @pytest.mark.asyncio
    async def test_full_flow_all_tiers_fail(self, state_manager, sample_ocr_job):
        """
        Test flow where all tiers fail validation.

        Scenario:
        1. Last tier (llm_cloud) produces invalid output
        2. No remaining tiers
        3. Completion message sent with failed status
        """
        state = PendingValidationState(
            original_job=sample_ocr_job,
            image_index=0,
            tier_name="llm_cloud",  # Last tier
            ocr_text="still garbled output",
            remaining_tiers=[],  # No more tiers
            processed_results=[],
            validation_job_id="val-003",
            created_at="2026-02-03T12:00:00Z"
        )
        state_manager.save(state)

        callback_payload = ValidationCallbackPayload(
            job_id="llm-job-003",
            status="succeeded",
            result={"content": json.dumps({
                "is_valid": False,
                "confidence": 0.1,
                "reason": "Unable to extract readable text"
            })},
            metadata={
                "validation_state_key": "val-003",
                "ocr_job_id": "ocr-job-123",
                "workflow_id": "wf-456",
                "image_index": 0,
                "tier_name": "llm_cloud"
            }
        )

        with patch('app.validation_callback.get_state_manager', return_value=state_manager), \
             patch('app.continue_processing.queue_client') as mock_queue:
            mock_queue.enqueue.return_value = True

            await validation_callback(callback_payload)

            # Verify completion sent with failed status
            mock_queue.enqueue.assert_called_once()
            message = mock_queue.enqueue.call_args[0][1]

            assert message["job_type"] == "ocr.completed"
            assert message["payload"]["status"] == "failed"
            assert message["payload"]["results"][0]["meta"]["is_valid"] is False

    @pytest.mark.asyncio
    async def test_multi_image_flow(self, state_manager):
        """
        Test flow with multiple images.

        Scenario:
        1. First image completes successfully
        2. Second image processing starts
        """
        multi_image_job = {
            "job_id": "ocr-multi-123",
            "workflow_id": "wf-multi-456",
            "reply_to": "jarvis.recipes.jobs",
            "source": "jarvis-recipes-server",
            "payload": {
                "image_refs": [
                    {"index": 0, "kind": "local_path", "value": "/img1.jpg"},
                    {"index": 1, "kind": "local_path", "value": "/img2.jpg"}
                ],
                "image_count": 2,
                "options": {"language": "en"}
            },
            "trace": {"request_id": "req-multi", "parent_job_id": "parent-multi"}
        }

        state = PendingValidationState(
            original_job=multi_image_job,
            image_index=0,
            tier_name="tesseract",
            ocr_text="First image text",
            remaining_tiers=[],
            processed_results=[],
            validation_job_id="val-multi-001",
            created_at="2026-02-03T12:00:00Z"
        )
        state_manager.save(state)

        callback_payload = ValidationCallbackPayload(
            job_id="llm-multi-001",
            status="succeeded",
            result={"content": json.dumps({
                "is_valid": True,
                "confidence": 0.9,
                "reason": "Valid text"
            })},
            metadata={
                "validation_state_key": "val-multi-001",
                "ocr_job_id": "ocr-multi-123",
                "workflow_id": "wf-multi-456",
                "image_index": 0,
                "tier_name": "tesseract"
            }
        )

        with patch('app.validation_callback.get_state_manager', return_value=state_manager), \
             patch('app.continue_processing._process_next_image', new_callable=AsyncMock) as mock_next_image:

            await validation_callback(callback_payload)

            # Verify next image processing was started
            mock_next_image.assert_called_once()
            call_args = mock_next_image.call_args[0]
            assert call_args[2] == 1  # next_image_index


class TestLLMQueueClientIntegration:
    """Integration tests for LLM queue client."""

    def test_build_payload_structure(self):
        """Verify payload structure matches LLM proxy expectations."""
        client = LLMQueueClient(
            llm_proxy_url="http://10.0.0.122:8000",
            app_id="ocr-service",
            app_key="test-key"
        )

        state = PendingValidationState(
            original_job={
                "job_id": "ocr-123",
                "workflow_id": "wf-456"
            },
            image_index=0,
            tier_name="tesseract",
            ocr_text="Sample OCR text for validation",
            remaining_tiers=[],
            processed_results=[],
            validation_job_id="val-integration-001",
            created_at="2026-02-03T12:00:00Z"
        )

        payload = client._build_payload(state, "http://10.0.0.71:7031/internal/validation/callback")

        # Verify required fields for LLM proxy queue
        assert "job_id" in payload
        assert "job_type" in payload
        assert "request" in payload
        assert "callback" in payload
        assert "metadata" in payload

        # Verify callback structure
        assert payload["callback"]["url"] == "http://10.0.0.71:7031/internal/validation/callback"
        assert payload["callback"]["method"] == "POST"

        # Verify metadata has all needed fields for callback
        metadata = payload["metadata"]
        assert "validation_state_key" in metadata
        assert "ocr_job_id" in metadata
        assert "workflow_id" in metadata
        assert "image_index" in metadata
        assert "tier_name" in metadata


class TestStateRoundtrip:
    """Test state serialization roundtrip."""

    def test_complex_state_roundtrip(self):
        """Complex state should survive JSON roundtrip."""
        original = PendingValidationState(
            original_job={
                "job_id": "ocr-complex-123",
                "workflow_id": "wf-complex-456",
                "reply_to": "jarvis.recipes.jobs",
                "source": "jarvis-recipes-server",
                "payload": {
                    "image_refs": [
                        {"index": 0, "kind": "s3", "value": "s3://bucket/img.jpg"},
                        {"index": 1, "kind": "local_path", "value": "/local/img2.jpg"}
                    ],
                    "image_count": 2,
                    "options": {"language": "en"}
                },
                "trace": {"request_id": "req-complex", "parent_job_id": "parent-complex"}
            },
            image_index=1,
            tier_name="apple_vision",
            ocr_text="Complex text with\nmultiple lines\nand unicode: é à ü",
            remaining_tiers=["llm_local", "llm_cloud"],
            processed_results=[{
                "index": 0,
                "ocr_text": "First image result",
                "truncated": False,
                "meta": {"is_valid": True, "confidence": 0.85}
            }],
            validation_job_id="val-complex-001",
            created_at="2026-02-03T15:30:00Z"
        )

        json_str = original.to_json()
        restored = PendingValidationState.from_json(json_str)

        assert restored.original_job == original.original_job
        assert restored.image_index == original.image_index
        assert restored.tier_name == original.tier_name
        assert restored.ocr_text == original.ocr_text
        assert restored.remaining_tiers == original.remaining_tiers
        assert restored.processed_results == original.processed_results
        assert restored.validation_job_id == original.validation_job_id
