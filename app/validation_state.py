"""Validation state management for async LLM validation flow."""

import json
import logging
from dataclasses import dataclass, asdict
from typing import Dict, Any, List, Optional, Union

logger = logging.getLogger(__name__)


@dataclass
class PendingValidationState:
    """State stored in Redis while waiting for LLM validation callback."""

    original_job: Dict[str, Any]
    image_index: int
    tier_name: str
    ocr_text: str
    remaining_tiers: List[str]
    processed_results: List[Dict[str, Any]]
    validation_job_id: str
    created_at: str

    def to_json(self) -> str:
        """Serialize state to JSON string."""
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, json_data: Union[str, bytes]) -> "PendingValidationState":
        """Deserialize state from JSON string or bytes."""
        if isinstance(json_data, bytes):
            json_data = json_data.decode('utf-8')
        data = json.loads(json_data)
        return cls(**data)


class ValidationStateManager:
    """Manages pending validation state in Redis."""

    KEY_PREFIX = "ocr:pending_validation:"
    DEFAULT_TTL = 300  # 5 minutes

    def __init__(
        self,
        redis_client: Any,
        ttl: int = DEFAULT_TTL
    ):
        """
        Initialize the state manager.

        Args:
            redis_client: Redis client instance
            ttl: Time-to-live in seconds for state entries
        """
        self._redis = redis_client
        self._ttl = ttl

    @property
    def key_prefix(self) -> str:
        """Return the key prefix for state entries."""
        return self.KEY_PREFIX

    def _make_key(self, validation_job_id: str) -> str:
        """Create Redis key from validation job ID."""
        return f"{self.KEY_PREFIX}{validation_job_id}"

    def save(self, state: PendingValidationState) -> None:
        """
        Save pending validation state to Redis.

        Args:
            state: State to save
        """
        key = self._make_key(state.validation_job_id)
        json_data = state.to_json()
        self._redis.setex(key, self._ttl, json_data)
        logger.debug(f"Saved validation state: {key}")

    def get(self, validation_job_id: str) -> Optional[PendingValidationState]:
        """
        Get pending validation state from Redis.

        Args:
            validation_job_id: The validation job ID to look up

        Returns:
            PendingValidationState if found, None otherwise
        """
        key = self._make_key(validation_job_id)
        data = self._redis.get(key)

        if data is None:
            return None

        try:
            return PendingValidationState.from_json(data)
        except (json.JSONDecodeError, TypeError, KeyError) as e:
            logger.error(f"Failed to deserialize validation state {key}: {e}")
            return None

    def delete(self, validation_job_id: str) -> None:
        """
        Delete pending validation state from Redis.

        Args:
            validation_job_id: The validation job ID to delete
        """
        key = self._make_key(validation_job_id)
        self._redis.delete(key)
        logger.debug(f"Deleted validation state: {key}")
