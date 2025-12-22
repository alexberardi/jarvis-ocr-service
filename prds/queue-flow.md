# OCR Service Queue Spec

## Purpose
`jarvis-ocr-service` consumes OCR jobs from Redis, extracts text from images, computes validity/confidence, and emits a completion message back to the caller’s queue so downstream services (e.g., recipes) can continue processing.

This doc specifies the OCR service responsibilities, message contracts, worker behavior, and operational guardrails.

## Scope
In-scope (v1):
- Consume jobs from `jarvis.ocr.jobs`
- Perform OCR on 1–8 referenced images per job using a tiered pipeline (Tesseract → EasyOCR → PaddleOCR → Apple Vision → LLM proxy local → LLM proxy cloud), short-circuiting per image on first passing tier
- Compute:
  - `ocr_text` (extracted text)
  - `is_valid` (boolean)
  - `confidence` (0.0–1.0)
  - `text_len` (int)
- Enforce max payload size for each image result `ocr_text` (50 KB per image)
- Emit `ocr.completed` event back to `reply_to` queue
- Retry policy + failure events

Out-of-scope (v1):
- Persisting OCR artifacts (text storage)
- PDF/multi-page support (unless already supported and kept within size limits)
- Advanced routing/priority lanes

## Queue & Connectivity
- **Input queue (consumed by OCR):** `jarvis.ocr.jobs`
- **Output queue (produced by OCR):** caller-provided `reply_to` (e.g., `jarvis.recipes.jobs`)

Networking assumption (v1):
- Redis is reachable via host-port mapping from inside containers.
- Default env:
  - `REDIS_HOST=host.docker.internal`
  - `REDIS_PORT=6379`

Linux fallback:
- `extra_hosts: ["host.docker.internal:host-gateway"]`

## Worker “Trigger” Model
The worker is event-driven via blocking reads (e.g., RQ worker blocking on queue). No HTTP triggers.

- One or more OCR worker processes listen on `jarvis.ocr.jobs`
- When a job arrives, a worker pops it immediately and processes it

## Message Contracts
Redis queues don’t have columns; all messages are JSON. OCR validates incoming messages and fails fast on schema violations.

### Common Envelope (v1)
```json
{
  "schema_version": 1,
  "job_id": "uuid",
  "workflow_id": "uuid",
  "job_type": "string",
  "source": "string",
  "target": "string",
  "created_at": "ISO-8601",
  "attempt": 1,
  "reply_to": "optional queue name",
  "payload": {},
  "trace": {
    "request_id": "optional",
    "parent_job_id": "optional"
  }
}
```

### OCR Request
- `job_type = "ocr.extract_text.requested"`
- Required:
  - `payload.image_refs[]` (1–8) with `kind`, `value`, and `index`
  - `reply_to`

```json
{
  "schema_version": 1,
  "job_id": "...",
  "workflow_id": "...",
  "job_type": "ocr.extract_text.requested",
  "source": "jarvis-recipes-server",
  "target": "jarvis-ocr-service",
  "created_at": "...",
  "attempt": 1,
  "reply_to": "jarvis.recipes.jobs",
  "payload": {
    "image_refs": [
      { "kind": "local_path|s3|minio|db", "value": "s3://my-bucket/recipe-images/<user_id>/<ingestion_id>/0.jpg", "index": 0 },
      { "kind": "local_path|s3|minio|db", "value": "s3://my-bucket/recipe-images/<user_id>/<ingestion_id>/1.jpg", "index": 1 }
    ],
    "image_count": 2,
    "options": {
      "language": "en"
    }
  },
  "trace": {
    "request_id": "...",
    "parent_job_id": null
  }
}
```

### OCR Completion Event
- `job_type = "ocr.completed"`
- Produced to `reply_to`
- Includes OCR output directly (v1) with a **50 KB max per image**

```json
{
  "schema_version": 1,
  "job_id": "...",
  "workflow_id": "...",
  "job_type": "ocr.completed",
  "source": "jarvis-ocr-service",
  "target": "<caller>",
  "created_at": "...",
  "attempt": 1,
  "reply_to": null,
  "payload": {
    "status": "success|failed",
    "results": [
      {
        "index": 0,
        "ocr_text": "<full extracted text for image 0, may be truncated>",
        "truncated": false,
        "meta": {
          "language": "en",
          "confidence": 0.0,
          "text_len": 0,
          "is_valid": true,
          "tier": "tesseract|easyocr|paddleocr|apple_vision|llm_local|llm_cloud",
          "validation_reason": "optional, <=200 chars"
        },
        "error": null
      },
      {
        "index": 1,
        "ocr_text": "<full extracted text for image 1, may be truncated>",
        "truncated": false,
        "meta": {
          "language": "en",
          "confidence": 0.0,
          "text_len": 0,
          "is_valid": true,
          "tier": "tesseract|easyocr|paddleocr|apple_vision|llm_local|llm_cloud",
          "validation_reason": "optional, <=200 chars"
        },
        "error": null
      }
    ],
    "artifact_ref": null,
    "error": {
      "message": "optional",
      "code": "optional"
    }
  },
  "trace": {
    "request_id": "...",
    "parent_job_id": "<ocr.request job_id>"
  }
}
```

## Locked JSON Schemas (v1)
These schemas are the canonical contracts for queue messages and the lightweight LLM validity response.

Notes:
- Messages MUST be valid JSON.
- Consumers MUST reject messages that fail schema validation.
- `schema_version` is fixed to `1` for v1.
- `created_at` MUST be ISO-8601 (UTC recommended).
- `job_id` and `workflow_id` SHOULD be UUID strings.

### Schema: OCR Request (`ocr.extract_text.requested`)
```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "jarvis.ocr.request.v1",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "schema_version",
    "job_id",
    "workflow_id",
    "job_type",
    "source",
    "target",
    "created_at",
    "attempt",
    "reply_to",
    "payload",
    "trace"
  ],
  "properties": {
    "schema_version": { "const": 1 },
    "job_id": { "type": "string" },
    "workflow_id": { "type": "string" },
    "job_type": { "const": "ocr.extract_text.requested" },
    "source": { "type": "string", "minLength": 1 },
    "target": { "type": "string", "minLength": 1 },
    "created_at": { "type": "string", "format": "date-time" },
    "attempt": { "type": "integer", "minimum": 1 },
    "reply_to": { "type": "string", "minLength": 1 },
    "payload": {
      "type": "object",
      "additionalProperties": false,
      "required": ["image_refs", "image_count"],
      "properties": {
        "image_refs": {
          "type": "array",
          "minItems": 1,
          "maxItems": 8,
          "items": {
            "type": "object",
            "additionalProperties": false,
            "required": ["kind", "value", "index"],
            "properties": {
              "kind": {
                "type": "string",
                "enum": ["local_path", "s3", "minio", "db"]
              },
              "value": { "type": "string", "minLength": 1 },
              "index": { "type": "integer", "minimum": 0 }
            }
          }
        },
        "image_count": { "type": "integer", "minimum": 1, "maximum": 8 },
        "options": {
          "type": "object",
          "additionalProperties": false,
          "properties": {
            "language": { "type": "string", "minLength": 1 }
          }
        }
      }
    },
    "trace": {
      "type": "object",
      "additionalProperties": false,
      "required": ["request_id", "parent_job_id"],
      "properties": {
        "request_id": { "type": ["string", "null"] },
        "parent_job_id": { "type": ["string", "null"] }
      }
    }
  }
}
```

### Schema: OCR Completion (`ocr.completed`)
```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "jarvis.ocr.completed.v1",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "schema_version",
    "job_id",
    "workflow_id",
    "job_type",
    "source",
    "target",
    "created_at",
    "attempt",
    "reply_to",
    "payload",
    "trace"
  ],
  "properties": {
    "schema_version": { "const": 1 },
    "job_id": { "type": "string" },
    "workflow_id": { "type": "string" },
    "job_type": { "const": "ocr.completed" },
    "source": { "const": "jarvis-ocr-service" },
    "target": { "type": "string", "minLength": 1 },
    "created_at": { "type": "string", "format": "date-time" },
    "attempt": { "type": "integer", "minimum": 1 },
    "reply_to": { "type": ["string", "null"] },
    "payload": {
      "type": "object",
      "additionalProperties": false,
      "required": ["status", "results", "artifact_ref", "error"],
      "properties": {
        "status": { "type": "string", "enum": ["success", "failed"] },
        "results": {
          "type": "array",
          "minItems": 1,
          "maxItems": 8,
          "items": {
            "type": "object",
            "additionalProperties": false,
            "required": ["index", "ocr_text", "truncated", "meta", "error"],
            "properties": {
              "index": { "type": "integer", "minimum": 0 },
              "ocr_text": { "type": "string" },
              "truncated": { "type": "boolean" },
              "meta": {
                "type": "object",
                "additionalProperties": false,
                "required": ["language", "confidence", "text_len", "is_valid", "tier"],
                "properties": {
                  "language": { "type": "string", "minLength": 1 },
                  "confidence": { "type": "number", "minimum": 0.0, "maximum": 1.0 },
                  "text_len": { "type": "integer", "minimum": 0 },
                  "is_valid": { "type": "boolean" },
                  "tier": {
                    "type": "string",
                    "enum": ["tesseract", "easyocr", "paddleocr", "apple_vision", "llm_local", "llm_cloud"]
                  },
                  "validation_reason": { "type": "string", "maxLength": 200 }
                }
              },
              "error": {
                "type": ["object", "null"],
                "additionalProperties": false,
                "required": ["message", "code"],
                "properties": {
                  "message": { "type": ["string", "null"] },
                  "code": { "type": ["string", "null"] }
                }
              }
            }
          }
        },
        "artifact_ref": { "type": ["object", "null"] },
        "error": {
          "type": ["object", "null"],
          "additionalProperties": false,
          "required": ["message", "code"],
          "properties": {
            "message": { "type": ["string", "null"] },
            "code": { "type": ["string", "null"] }
          }
        }
      }
    },
    "trace": {
      "type": "object",
      "additionalProperties": false,
      "required": ["request_id", "parent_job_id"],
      "properties": {
        "request_id": { "type": ["string", "null"] },
        "parent_job_id": { "type": ["string", "null"] }
      }
    }
  }
}
```

### Schema: LLM Validity Response (strict JSON-only)
The lightweight validator MUST return exactly one JSON object with these keys.

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "jarvis.ocr.validator_response.v1",
  "type": "object",
  "additionalProperties": false,
  "required": ["is_valid", "confidence", "reason"],
  "properties": {
    "is_valid": { "type": "boolean" },
    "confidence": { "type": "number", "minimum": 0.0, "maximum": 1.0 },
    "reason": { "type": "string", "maxLength": 200 }
  }
}
```

#### Validator prompt requirements
- Output must be a single JSON object (no code fences, no extra text).
- Set `max_new_tokens` (ex: 120–200).
- Use a stop sequence (ex: newline) by requiring one-line JSON.

## Processing Pipeline (v1)
### 1) Validate input
On job receipt:
- Validate JSON parse
- Validate required envelope fields (`schema_version`, `job_id`, `workflow_id`, `job_type`)
- Validate `reply_to` is present
- Validate `payload.image_refs[]` exists and has 1–8 items
- Validate each item has `kind`, `value`, `index`
- If invalid → emit `ocr.completed` with `status=failed` and `error.code="bad_request"`

### 2) Resolve image references
Supported v1:
- `local_path`: path must be accessible inside OCR container (bind mount or shared volume)
- `s3/minio`: full URI supported (e.g., `s3://bucket/key` or HTTPS). OCR must have credentials/permissions.

If an image cannot be resolved/read:
- Add a failed entry for that index in `results[]` with `is_valid=false` and `results[i].error.code="image_not_found"`.
- Continue processing remaining images.

### 3) Tiered OCR pipeline (per image, short-circuit)
For each `image_refs[i]`:
- Run tiers in order:
  1. Tesseract
  2. EasyOCR
  3. PaddleOCR
  4. Apple Vision
  5. LLM proxy (local)
  6. LLM proxy (cloud / ChatGPT)

Per tier:
- Extract candidate text
- Normalize minimally (strip nulls, normalize newlines, collapse extreme whitespace)
- Run lightweight LLM validation on the candidate text to produce:
  - `is_valid`
  - `validation_reason` (<=200 chars)
  - optional validator confidence
- If `is_valid=true` (and optional `confidence >= OCR_MIN_CONFIDENCE` if configured) → accept this tier and stop trying further tiers for that image.

If all tiers fail validation for an image:
- Return a result entry with `is_valid=false`, `tier="llm_cloud"` (or the last attempted tier), and `results[i].error.code="ocr_no_valid_output"`.

### 4) Confidence calculation
- If the OCR tier provides native confidence, normalize to 0.0–1.0.
- Otherwise use validator confidence if provided; else fallback to a heuristic confidence.

### 5) Enforce payload limits
Max OCR text size in completion message:
- **50 KB per image** for `results[i].ocr_text`

If exceeded:
- truncate to <= 50 KB
- set `results[i].truncated=true`

### 6) Emit completion event
- Always emit an `ocr.completed` message to the `reply_to` queue.
- `payload.status` is:
  - `success` if at least one image produced `is_valid=true`
  - `failed` if all images failed
- Always include:
  - `workflow_id`
  - `trace.parent_job_id` = original OCR request `job_id`
  - `results[]` aligned by `index`
  - top-level `error` only when `payload.status="failed"`
  - Each `results[i]` must include `error` (null on success; {code,message} on per-image failure).

## Retries & Failure Handling
### Retry policy (v1)
- Max attempts: `3`
- Retry on transient errors:
  - OCR engine crash
  - temporary file read errors
  - temporary Redis errors
  - Note: individual image failures are captured in `results[]`; retries apply to job-level transient failures (e.g., Redis outage, worker crash).

Do not retry (fail fast):
- schema invalid
- missing `reply_to`
- image missing/unreadable (unless you know it’s a transient mount timing issue)

### Failure event
On any terminal failure, emit `ocr.completed` with:
- `payload.status = "failed"`
- `payload.error.code` set
- `payload.error.message` brief

## Resolved Decisions (v1)
1. Multiple images: use `payload.image_refs[]` (1–8) and return `payload.results[]` aligned by `index`.
2. Image refs: prefer full URIs (e.g., `s3://bucket/key` or HTTPS) so OCR is decoupled from bucket location.
3. Validator model: default `OCR_VALIDATION_MODEL="llm_local_light"` (override via env per host).
4. Confidence: informational only in v1 (no `OCR_MIN_CONFIDENCE` gate).
5. PDF support: explicitly reject PDFs in v1 (fail fast with `error.code="unsupported_media"`).
6. Local path convention: use `/data/images/...` as the in-container mount root when `kind=local_path`.
7. Retry re-queue position: requeue to the **back** (RPUSH) to avoid starving other jobs.
8. Validation reason: include `meta.validation_reason` (<=200 chars) for debugging and log it at `INFO` on success and `WARN` on failure.
9. Per-image error reporting: each `results[i]` includes `error` (null or {code,message}) so partial failures are debuggable without artifact storage.

## Observability
Log per job:
- `job_id`, `workflow_id`, `job_type`, `attempt`
- start/end timestamps
- duration
- `is_valid`, `confidence`, `text_len`, `truncated`

Recommended metrics:
- jobs processed/sec
- failure rate by `error.code`
- average OCR latency

## Configuration
Env vars (suggested):
- `REDIS_HOST`
- `REDIS_PORT`
- `OCR_MAX_TEXT_BYTES` (default 51200)
- `OCR_MIN_VALID_CHARS` (default TBD)
- `OCR_LANGUAGE_DEFAULT` (default "en")
- `OCR_MAX_ATTEMPTS` (default 3)
- `OCR_VALIDATION_MODEL` (default "llm_local_light")
- `OCR_MIN_CONFIDENCE` (default unset; informational only in v1)
- `OCR_ENABLED_TIERS` (default "tesseract,easyocr,paddleocr,apple_vision,llm_local,llm_cloud")

## Open Questions

### Implementation Questions (2024-12-20)

1. **Dependencies for S3/MinIO/HTTPS support (RESOLVED)**: Make `boto3` and `requests` required dependencies for v1.
   - Rationale: URI-based `image_refs` are a core contract; fetch support must be reliable out of the box.
   - Local-only users can still use `local_path`, but dependencies remain installed.

2. **MinIO custom endpoint configuration (RESOLVED)**: Add explicit endpoint env vars.
   - New env vars:
     - `S3_ENDPOINT_URL` (optional; if set, pass to boto3 as `endpoint_url`)
     - `S3_REGION` (optional; default "us-east-2")
     - `S3_FORCE_PATH_STYLE` (optional; default false; set true for many MinIO setups)
   - Guidance:
     - AWS S3: leave `S3_ENDPOINT_URL` unset.
     - MinIO: set `S3_ENDPOINT_URL=http://<host>:9000` (or https), and likely `S3_FORCE_PATH_STYLE=true`.

3. **Error code for PDF rejection (RESOLVED)**: Use `unsupported_media` as the per-image error code and preserve partial success.
   - Behavior:
     - If any `image_refs[i]` points to a PDF (or is detected as PDF), create a `results[]` entry for that `index` with `is_valid=false` and `error.code="unsupported_media"`.
     - Continue processing remaining images.
     - Top-level `payload.status` follows the existing rule: `success` if at least one image is valid; otherwise `failed`.
   - Note: keep the top-level `payload.error` for the case where **all** images fail.

### Historical Questions (Resolved)

1. ~~What lightweight LLM model should be the default for OCR validity checks?~~
   - **Resolved**: Default is `OCR_VALIDATION_MODEL="llm_local_light"` (per Resolved Decisions #3)

2. ~~Do we want to require a minimum confidence (`OCR_MIN_CONFIDENCE`) for acceptance, or treat confidence as informational only?~~
   - **Resolved**: Informational only in v1 (per Resolved Decisions #4)

3. ~~Do we need PDF support in v1, or explicitly reject it?~~
   - **Resolved**: Explicitly reject PDFs in v1 (per Resolved Decisions #5)

4. ~~How will `local_path` images be shared into the OCR container (bind mount path convention)?~~
   - **Resolved**: Use `/data/images/...` as the in-container mount root (per Resolved Decisions #6)

5. ~~For retry logic, should failed jobs be re-queued to the front (LPUSH) or back (RPUSH) of the queue?~~
   - **Resolved**: Re-queue to the back (RPUSH) to avoid starving other jobs (per Resolved Decisions #7)

6. ~~Should the worker log the validation `reason` field from LLM responses, or is it only needed in completion messages?~~
   - **Resolved**: Include `meta.validation_reason` (<=200 chars) for debugging and log it at INFO on success and WARN on failure (per Resolved Decisions #8)