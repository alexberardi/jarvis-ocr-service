"""Redis queue client for status checking and job management."""

import json
import uuid
import logging
from datetime import datetime
from typing import Optional, Dict, Any

from app.config import config

logger = logging.getLogger(__name__)

# Try to import redis, but it's optional
try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    redis = None

# Try to import RQ (Redis Queue) for job processing
try:
    from rq import Queue
    RQ_AVAILABLE = True
except ImportError:
    RQ_AVAILABLE = False
    Queue = None


class QueueClient:
    """Client for checking Redis queue status."""
    
    def __init__(self):
        self.host = config.REDIS_HOST
        self.port = config.REDIS_PORT
        self.queue_name = "jarvis.ocr.jobs"  # Queue name per PRD
        self.jobs_key_prefix = "ocr_job:"  # Prefix for job status keys
        self._client: Optional[Any] = None
    
    def _get_client(self):
        """Get or create Redis client."""
        if not REDIS_AVAILABLE:
            return None
        
        if self._client is None:
            try:
                self._client = redis.Redis(
                    host=self.host,
                    port=self.port,
                    password=config.REDIS_PASSWORD,
                    decode_responses=False,  # Keep binary for compatibility
                    socket_connect_timeout=5,  # Connection timeout
                    socket_timeout=None  # No timeout for blocking operations (brpop can block)
                )
                # Test connection
                self._client.ping()
            except Exception as e:
                logger.warning(f"Failed to connect to Redis: {e}")
                self._client = None
        
        return self._client
    
    def get_status(self) -> Dict[str, Any]:
        """
        Get queue status and Redis information.
        
        Returns:
            Dict with queue status information
        """
        client = self._get_client()
        
        if client is None:
            return {
                "redis_connected": False,
                "queue_length": 0,
                "workers_active": 0,
                "queue_name": self.queue_name,
                "redis_info": {
                    "host": self.host,
                    "port": self.port,
                    "version": "unknown"
                },
                "error": "Redis not available or not configured"
            }
        
        try:
            # Get queue length
            queue_length = client.llen(self.queue_name)
            
            # Get Redis info
            info = client.info()
            redis_version = info.get(b"redis_version", b"unknown").decode("utf-8", errors="ignore")
            
            # Workers active (not tracked yet, placeholder)
            workers_active = 0
            
            return {
                "redis_connected": True,
                "queue_length": queue_length,
                "workers_active": workers_active,
                "queue_name": self.queue_name,
                "redis_info": {
                    "host": self.host,
                    "port": self.port,
                    "version": redis_version
                }
            }
        
        except Exception as e:
            logger.error(f"Error getting queue status: {e}")
            return {
                "redis_connected": False,
                "queue_length": 0,
                "workers_active": 0,
                "queue_name": self.queue_name,
                "redis_info": {
                    "host": self.host,
                    "port": self.port,
                    "version": "unknown"
                },
                "error": str(e)
            }
    
    def enqueue_job(self, job_data: Dict[str, Any]) -> str:
        """
        Enqueue an OCR job to Redis.
        
        Args:
            job_data: Job data dictionary (OCR request)
        
        Returns:
            Job ID (UUID string)
        """
        client = self._get_client()
        
        if client is None:
            raise RuntimeError("Redis not available - cannot enqueue job")
        
        # Generate job ID
        job_id = str(uuid.uuid4())
        
        # Create job payload
        job_payload = {
            "job_id": job_id,
            "created_at": datetime.utcnow().isoformat() + "Z",
            "status": "pending",
            "request": job_data
        }
        
        try:
            # Store job status in Redis (with TTL of 24 hours)
            job_key = f"{self.jobs_key_prefix}{job_id}"
            client.setex(
                job_key,
                86400,  # 24 hours TTL
                json.dumps(job_payload)
            )
            
            # Enqueue job to processing queue
            client.lpush(self.queue_name, json.dumps({
                "job_id": job_id,
                "request": job_data
            }))
            
            logger.info(f"Job enqueued: {job_id}")
            return job_id
            
        except Exception as e:
            logger.error(f"Failed to enqueue job: {e}")
            raise RuntimeError(f"Failed to enqueue job: {e}")
    
    def get_job_status(self, job_id: str) -> Optional[Dict[str, Any]]:
        """
        Get job status from Redis.
        
        Args:
            job_id: Job ID to look up
        
        Returns:
            Job status dictionary or None if not found
        """
        client = self._get_client()
        
        if client is None:
            return None
        
        try:
            job_key = f"{self.jobs_key_prefix}{job_id}"
            job_data = client.get(job_key)
            
            if job_data is None:
                return None
            
            # Decode if bytes
            if isinstance(job_data, bytes):
                job_data = job_data.decode('utf-8')
            
            return json.loads(job_data)
            
        except Exception as e:
            logger.error(f"Failed to get job status: {e}")
            return None
    
    def update_job_status(self, job_id: str, status: str, result: Optional[Dict[str, Any]] = None, error: Optional[str] = None) -> bool:
        """
        Update job status in Redis.
        
        Args:
            job_id: Job ID
            status: New status ("pending", "processing", "completed", "failed")
            result: Optional result data
            error: Optional error message
        
        Returns:
            True if updated successfully, False otherwise
        """
        client = self._get_client()
        
        if client is None:
            return False
        
        try:
            job_key = f"{self.jobs_key_prefix}{job_id}"
            current_job = self.get_job_status(job_id)
            
            if current_job is None:
                logger.warning(f"Job not found: {job_id}")
                return False
            
            # Update job status
            current_job["status"] = status
            current_job["updated_at"] = datetime.utcnow().isoformat() + "Z"
            
            if result is not None:
                current_job["result"] = result
            
            if error is not None:
                current_job["error"] = error
            
            # Update in Redis (keep existing TTL or set new 24h TTL)
            client.setex(
                job_key,
                86400,  # 24 hours TTL
                json.dumps(current_job)
            )
            
            logger.info(f"Job status updated: {job_id} -> {status}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to update job status: {e}")
            return False
    
    def dequeue_job(self, timeout: int = 0) -> Optional[Dict[str, Any]]:
        """
        Dequeue a job from Redis (for workers).
        
        Args:
            timeout: Blocking timeout in seconds (0 = non-blocking)
        
        Returns:
            Job dictionary or None if no jobs available
        """
        client = self._get_client()
        
        if client is None:
            return None
        
        try:
            if timeout > 0:
                # Blocking pop
                result = client.brpop(self.queue_name, timeout=timeout)
                if result is None:
                    return None
                # brpop returns (queue_name, value) tuple
                job_data = result[1]
            else:
                # Non-blocking pop
                job_data = client.rpop(self.queue_name)
                if job_data is None:
                    return None
            
            # Decode if bytes
            if isinstance(job_data, bytes):
                job_data = job_data.decode('utf-8')
            
            return json.loads(job_data)
            
        except Exception as e:
            logger.error(f"Failed to dequeue job: {e}")
            return None
    
    def enqueue(self, queue_name: str, message: Dict[str, Any], to_back: bool = False) -> bool:
        """
        Enqueue a message to a Redis queue.
        
        For OCR completion messages to jarvis.recipes.jobs, uses RQ's enqueue method.
        For other queues, uses raw Redis LPUSH/RPUSH.
        
        Args:
            queue_name: Target queue name
            message: Message dict (will be JSON-encoded)
            to_back: If True, use RPUSH (back of queue), else LPUSH (front)
                    (ignored for RQ queues, which always enqueue to back)
        
        Returns:
            True if enqueued successfully, False otherwise
        """
        # Check if this is an OCR completion message going to recipes queue
        # If so, use RQ's enqueue method as required by the recipes service
        if (queue_name == "jarvis.recipes.jobs" and 
            message.get("job_type") == "ocr.completed" and 
            RQ_AVAILABLE):
            return self._enqueue_with_rq(queue_name, message)
        
        # For all other queues, use raw Redis commands
        client = self._get_client()
        
        if client is None:
            return False
        
        try:
            message_json = json.dumps(message)
            if to_back:
                client.rpush(queue_name, message_json)
            else:
                client.lpush(queue_name, message_json)
            logger.debug(f"Enqueued message to queue: {queue_name} ({'back' if to_back else 'front'})")
            return True
            
        except Exception as e:
            logger.error(f"Failed to enqueue message to {queue_name}: {e}")
            return False
    
    def _enqueue_with_rq(self, queue_name: str, message: Dict[str, Any]) -> bool:
        """
        Enqueue an OCR completion message using RQ (Redis Queue).
        
        This method is used specifically for OCR completion events going to
        jarvis.recipes.jobs, as required by the recipes service.
        
        Args:
            queue_name: Target queue name (must be "jarvis.recipes.jobs")
            message: OCR completion message envelope
        
        Returns:
            True if enqueued successfully, False otherwise
        """
        if not RQ_AVAILABLE:
            logger.error("RQ (Redis Queue) not available - cannot enqueue OCR completion")
            return False
        
        client = self._get_client()
        if client is None:
            return False
        
        try:
            # Create RQ queue connection
            # RQ works best with decode_responses=True (default)
            # Create a separate connection for RQ if needed
            rq_redis = redis.Redis(
                host=self.host,
                port=self.port,
                password=config.REDIS_PASSWORD,
                decode_responses=True,  # RQ expects string responses
                socket_connect_timeout=5,
                socket_timeout=None
            )
            rq_queue = Queue(queue_name, connection=rq_redis)
            
            # Extract job_id from message
            job_id = message.get("job_id")
            if not job_id:
                logger.error("OCR completion message missing job_id")
                return False
            
            # Encode message as JSON string (as expected by recipes service)
            message_json = json.dumps(message)
            
            # Enqueue using RQ with the exact function path required by recipes service
            rq_queue.enqueue(
                "jarvis_recipes.app.services.queue_worker.process_job",
                message_json,
                job_id=job_id,
                job_timeout="10m"
            )
            
            logger.info(f"Enqueued OCR completion to RQ queue {queue_name} [job_id={job_id}]")
            return True
            
        except Exception as e:
            logger.error(f"Failed to enqueue OCR completion with RQ to {queue_name}: {e}")
            return False
    
    def publish_message(self, queue_name: str, message: Dict[str, Any], to_back: bool = False) -> bool:
        """
        Deprecated: Use enqueue() instead.
        Publish a message to a Redis queue.
        
        Args:
            queue_name: Target queue name
            message: Message dict (will be JSON-encoded)
            to_back: If True, use RPUSH (back of queue), else LPUSH (front)
        
        Returns:
            True if published successfully, False otherwise
        """
        return self.enqueue(queue_name, message, to_back)


# Global queue client instance
queue_client = QueueClient()

