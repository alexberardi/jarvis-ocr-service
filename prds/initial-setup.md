

# Jarvis OCR Service — Product Requirements Document (PRD)

## Overview

The **Jarvis OCR Service** is a standalone FastAPI-based microservice responsible for performing Optical Character Recognition (OCR) on images and documents. It is designed to integrate cleanly with the broader Jarvis ecosystem (e.g., `jarvis-recipes`, parse workers, future document pipelines) while remaining portable across platforms.

The service supports multiple OCR backends ("providers") behind a single, stable HTTP API. Some providers are optional and platform-specific. Provider availability is controlled entirely through environment variables.

The service must be able to:
- Run **natively on macOS** (for Apple Vision support and Metal-accelerated workflows)
- Run **inside Docker** (Linux/macOS) with non-Apple providers only
- Expose a consistent API regardless of enabled providers

---

## Goals

- Provide a **single OCR API** with pluggable backends
- Prefer **local-first** processing (no external SaaS dependencies)
- Allow **Apple Vision** as a high-quality, macOS-only accelerator
- Remain **Docker-compatible** when Apple Vision is disabled
- Be simple to operate, configure, and extend

---

## Non-Goals

- PDF parsing beyond basic image extraction (initially)
- Handwriting recognition guarantees (best-effort only)
- End-user UI (API-only service)
- Long-term document storage (stateless by default)

---

## Runtime & Deployment

### Server
- Framework: **FastAPI**
- ASGI server: **Uvicorn**
- Default port: **5009**
- Configurable via environment variable: `OCR_PORT`

Example:
```bash
OCR_PORT=5010 python main.py
```

### Native macOS Mode
- Required for **Apple Vision**
- Runs directly on macOS (no container)
- Python must have access to macOS system frameworks

### Docker Mode
- Supported when **Apple Vision is disabled**
- Must include:
  - Tesseract binaries
  - Python dependencies for enabled providers
- Apple Vision provider must be automatically disabled in Docker

---

## OCR Providers

### Mandatory Provider

#### Tesseract
- **Required**
- Must always be available
- Acts as the universal fallback
- Used when no other provider is enabled or available

---

### Optional Providers (Enabled via ENV)

Each optional provider is disabled by default and enabled explicitly via environment variables.

#### EasyOCR
- ENV: `OCR_ENABLE_EASYOCR=true`
- Cross-platform
- Good for noisy or stylized text
- Higher memory usage

#### PaddleOCR
- ENV: `OCR_ENABLE_PADDLEOCR=true`
- Cross-platform
- Strong layout and table detection
- Heavier dependency footprint

#### Apple Vision
- ENV: `OCR_ENABLE_APPLE_VISION=true`
- **macOS only**
- Highest quality for printed text
- Fastest performance on Apple Silicon
- **Cannot run in Docker**

If `OCR_ENABLE_APPLE_VISION=true` and the service detects it is running inside Docker, startup must fail fast with a clear error message.

---

## Provider Selection Logic

### Request-Level Selection
Clients may specify a provider preference:
```json
{
  "provider": "auto"
}
```

Allowed values:
- `auto`
- `tesseract`
- `easyocr`
- `paddleocr`
- `apple_vision`

### `auto` Resolution Order
1. Apple Vision (if enabled and available)
2. PaddleOCR (if enabled)
3. EasyOCR (if enabled)
4. Tesseract (always available)

---

## API Design

### `POST /v1/ocr`

Perform OCR on an image.

**Request**
```json
{
  "document_id": "optional-string",
  "provider": "auto",
  "image": {
    "content_type": "image/png",
    "base64": "..."
  },
  "options": {
    "language_hints": ["en"],
    "return_boxes": true,
    "mode": "document"
  }
}
```

**Response**
```json
{
  "provider_used": "apple_vision",
  "text": "Full extracted text...",
  "blocks": [
    {
      "text": "Example text",
      "bbox": [x, y, width, height],
      "confidence": 0.94
    }
  ],
  "meta": {
    "duration_ms": 123
  }
}
```

---

### `GET /v1/providers`

Returns which OCR providers are available on the current deployment.

**Response**
```json
{
  "providers": {
    "tesseract": true,
    "easyocr": false,
    "paddleocr": false,
    "apple_vision": true
  }
}
```

---

### `GET /health`

Simple health check.

**Response**
```json
{ "status": "ok" }
```

---

## Configuration (Environment Variables)

| Variable | Default | Description |
|--------|--------|-------------|
| `OCR_PORT` | `5009` | Port FastAPI binds to |
| `OCR_ENABLE_EASYOCR` | `false` | Enable EasyOCR provider |
| `OCR_ENABLE_PADDLEOCR` | `false` | Enable PaddleOCR provider |
| `OCR_ENABLE_APPLE_VISION` | `false` | Enable Apple Vision (macOS only) |
| `OCR_LOG_LEVEL` | `info` | Logging verbosity |

---

## Error Handling

- Provider unavailable → `400 Bad Request`
- Provider enabled but not supported on platform → **fail at startup**
- OCR failure → `422 Unprocessable Entity`
- Internal provider error → `500 Internal Server Error`

Errors must include:
- Provider name
- Clear human-readable reason
- Stable error code

---

## Logging & Observability

- Structured logs (JSON preferred)
- Log provider selection and timing
- Do **not** log extracted text by default
- Include request correlation IDs if provided

---

## Security (High-Level)

- No authentication defined in this document
- Service must be auth-ready (middleware-friendly)
- No file system writes by default
- Memory-only processing unless explicitly extended

Auth will be specified in a separate document.

---

## Future Considerations

- PDF ingestion pipeline
- Layout-aware extraction modes
- Handwriting specialization
- GPU-accelerated OCR models
- Batch OCR endpoints

---

## Open Questions

- Should OCR results ever be cached?
- Do we want a synchronous + async job model?
- Should language detection be automatic or explicit?
- Do we want confidence thresholds enforced centrally?

These can be addressed in follow-up PRDs.
