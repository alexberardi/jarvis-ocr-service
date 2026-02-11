#!/usr/bin/env python3
"""
OCR Queue Test Script

Tests OCR functionality by:
1. Queuing jobs to jarvis.ocr.jobs (Redis)
2. Worker processes and sends results to reply queue
3. Script reads results from reply queue

Requires:
- Redis running (REDIS_HOST, REDIS_PORT env vars)
- Worker running (python worker.py)
"""

import json
import os
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

import redis

# Configuration
REDIS_HOST = os.getenv("REDIS_HOST", "10.0.0.122")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "redis")
OCR_QUEUE = "jarvis.ocr.jobs"
REPLY_QUEUE = "jarvis.ocr.test.results"  # Our test reply queue

TEST_IMAGES_DIR = Path(__file__).parent / "test_images"
RESULTS_FILE = Path(__file__).parent / "test_results.json"


def get_redis_client():
    """Create Redis client."""
    client = redis.Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        password=REDIS_PASSWORD,
        decode_responses=True,
        socket_connect_timeout=5
    )
    # Test connection
    client.ping()
    return client


def discover_tests() -> dict[str, list[Path]]:
    """Discover test folders and their images."""
    tests = {}

    for test_dir in sorted(TEST_IMAGES_DIR.iterdir()):
        if test_dir.is_dir() and test_dir.name.startswith("test"):
            images = []
            for img_file in sorted(test_dir.iterdir()):
                if img_file.suffix.lower() in (".jpg", ".jpeg", ".png", ".gif", ".webp"):
                    images.append(img_file)
            if images:
                tests[test_dir.name] = images

    return tests


def create_ocr_message(test_name: str, images: list[Path]) -> dict:
    """Create an OCR request message for the queue."""
    job_id = str(uuid.uuid4())
    workflow_id = str(uuid.uuid4())

    # Create image refs with absolute paths
    image_refs = []
    for i, img_path in enumerate(images):
        image_refs.append({
            "kind": "local_path",
            "value": str(img_path.absolute()),  # Absolute path
            "index": i
        })

    return {
        "schema_version": 1,
        "job_id": job_id,
        "workflow_id": workflow_id,
        "job_type": "ocr.extract_text.requested",
        "source": "ocr-test-script",
        "target": "jarvis-ocr-service",
        "created_at": datetime.utcnow().isoformat() + "Z",
        "attempt": 1,
        "reply_to": REPLY_QUEUE,
        "payload": {
            "image_refs": image_refs,
            "image_count": len(image_refs),
            "options": {
                "language": "en"
            }
        },
        "trace": {
            "request_id": str(uuid.uuid4()),
            "parent_job_id": None
        }
    }


def queue_test(client: redis.Redis, test_name: str, images: list[Path]) -> str:
    """Queue a test job and return the job_id."""
    message = create_ocr_message(test_name, images)
    job_id = message["job_id"]

    # Queue to OCR jobs queue
    client.lpush(OCR_QUEUE, json.dumps(message))

    return job_id


def wait_for_result(client: redis.Redis, job_id: str, timeout: int = 120) -> dict | None:
    """Wait for result on reply queue."""
    start = time.time()

    while time.time() - start < timeout:
        # Check for messages on reply queue
        result = client.brpop(REPLY_QUEUE, timeout=5)

        if result:
            _, message_json = result
            message = json.loads(message_json)

            # Check if this is our job (match by parent_job_id in trace)
            if message.get("trace", {}).get("parent_job_id") == job_id:
                return message
            else:
                # Not our message, put it back (edge case for concurrent tests)
                client.rpush(REPLY_QUEUE, message_json)

    return None


def run_tests() -> dict:
    """Run all tests."""
    print(f"OCR Queue Test Runner")
    print(f"=====================")
    print(f"Redis: {REDIS_HOST}:{REDIS_PORT}")
    print(f"OCR Queue: {OCR_QUEUE}")
    print(f"Reply Queue: {REPLY_QUEUE}")
    print(f"Test images: {TEST_IMAGES_DIR}")

    # Connect to Redis
    try:
        client = get_redis_client()
        print(f"Connected to Redis")
    except Exception as e:
        print(f"ERROR: Cannot connect to Redis: {e}")
        sys.exit(1)

    # Discover tests
    tests = discover_tests()
    print(f"\nDiscovered {len(tests)} test(s):")
    for name, images in tests.items():
        print(f"  - {name}: {len(images)} image(s)")

    # Check queue status
    queue_len = client.llen(OCR_QUEUE)
    print(f"\nCurrent OCR queue length: {queue_len}")

    results = {
        "timestamp": datetime.now().isoformat(),
        "config": {
            "redis_host": REDIS_HOST,
            "redis_port": REDIS_PORT,
            "ocr_queue": OCR_QUEUE,
            "reply_queue": REPLY_QUEUE,
        },
        "tests": {}
    }

    # Run each test
    for test_name, images in tests.items():
        print(f"\n{'='*60}")
        print(f"Running {test_name} ({len(images)} image(s))...")
        print(f"  Images: {[img.name for img in images]}")

        # Queue the job
        job_id = queue_test(client, test_name, images)
        print(f"  Queued job: {job_id}")

        # Wait for result
        print(f"  Waiting for result (timeout: 120s)...")
        result = wait_for_result(client, job_id, timeout=120)

        if result:
            payload = result.get("payload", {})
            status = payload.get("status", "unknown")

            print(f"  Status: {status.upper()}")

            test_result = {
                "status": status,
                "images": [img.name for img in images],
                "job_id": job_id,
                "results": []
            }

            for img_result in payload.get("results", []):
                idx = img_result.get("index", 0)
                ocr_text = img_result.get("ocr_text", "")
                meta = img_result.get("meta", {})
                error = img_result.get("error")

                img_name = images[idx].name if idx < len(images) else f"image_{idx}"

                print(f"\n  --- Image {idx}: {img_name} ---")
                print(f"  Valid: {meta.get('is_valid', False)}")
                print(f"  Tier: {meta.get('tier', 'unknown')}")
                print(f"  Confidence: {meta.get('confidence', 0):.2f}")
                print(f"  Text length: {len(ocr_text)} chars")

                if ocr_text:
                    preview = ocr_text[:150].replace('\n', ' ')
                    print(f"  Preview: {preview}...")

                if error:
                    print(f"  Error: {error}")

                test_result["results"].append({
                    "image": img_name,
                    "index": idx,
                    "is_valid": meta.get("is_valid", False),
                    "tier": meta.get("tier"),
                    "confidence": meta.get("confidence"),
                    "text_length": len(ocr_text),
                    "text": ocr_text,
                    "truncated": img_result.get("truncated", False),
                    "error": error
                })

            results["tests"][test_name] = test_result
        else:
            print(f"  TIMEOUT - no result received")
            results["tests"][test_name] = {
                "status": "timeout",
                "images": [img.name for img in images],
                "job_id": job_id,
                "error": "Timeout waiting for result"
            }

    return results


def main():
    """Main entry point."""
    results = run_tests()

    # Write results
    with open(RESULTS_FILE, "w") as f:
        json.dump(results, f, indent=2)

    print(f"\n{'='*60}")
    print(f"Results written to: {RESULTS_FILE}")

    # Summary
    success = sum(1 for t in results["tests"].values() if t.get("status") == "success")
    failed = len(results["tests"]) - success
    print(f"\nSummary: {success} passed, {failed} failed/timeout")


if __name__ == "__main__":
    main()
