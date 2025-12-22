# Jarvis OCR Service

A FastAPI-based microservice for Optical Character Recognition (OCR) with pluggable backends.

## Features

- **Multiple OCR Providers**: Tesseract (mandatory), EasyOCR, PaddleOCR, and Apple Vision (macOS only)
- **Auto Provider Selection**: Automatically selects the best available provider
- **Docker Support**: Runs in Docker (without Apple Vision) or natively on macOS
- **RESTful API**: Clean HTTP API with JSON request/response
- **Structured Logging**: JSON-formatted logs for observability

## Quick Start

### Native macOS (with Apple Vision support)

**Prerequisites:**
- Install Poetry: `curl -sSL https://install.python-poetry.org | python3 -`
- Install Tesseract: `brew install tesseract`

**Option 1: Using the run script (recommended)**
```bash
./run.sh
```

**Option 2: Manual setup with Poetry**
```bash
# Install core dependencies
poetry install

# For optional providers (install as needed)
# EasyOCR
poetry add --group optional easyocr

# PaddleOCR
poetry add --group optional paddlepaddle paddleocr

# Apple Vision (macOS only)
poetry add --group optional pyobjc-framework-Vision

# Run the service
poetry run python main.py
```

**Option 3: Manual setup with pip (legacy)**
```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run the service
python main.py
```

### Docker

```bash
# Build the image
docker build -t jarvis-ocr .

# Run the container
docker run -p 5009:5009 jarvis-ocr
```

## Configuration

Configuration is managed via environment variables. You can set them directly or use a `.env` file in the project root.

**Location**: Create a `.env` file in the project root directory (same level as `main.py` and `requirements.txt`).

Example `.env` file:
```bash
# Server Configuration
OCR_PORT=5009
OCR_LOG_LEVEL=info

# Provider Configuration
OCR_ENABLE_EASYOCR=false
OCR_ENABLE_PADDLEOCR=false
OCR_ENABLE_APPLE_VISION=false

# Auth Configuration
JARVIS_AUTH_BASE_URL=http://localhost:8000
JARVIS_APP_AUTH_CACHE_TTL_SECONDS=60
```

Set environment variables to configure the service:

### Server Configuration
- `OCR_PORT`: Port to bind (default: 5009)
- `OCR_LOG_LEVEL`: Logging level (default: info)

### Provider Configuration
- `OCR_ENABLE_EASYOCR`: Enable EasyOCR (default: false)
- `OCR_ENABLE_PADDLEOCR`: Enable PaddleOCR (default: false)
- `OCR_ENABLE_APPLE_VISION`: Enable Apple Vision (default: false, macOS only)

### Authentication Configuration
- `JARVIS_AUTH_BASE_URL`: Base URL for Jarvis Auth service (required for protected endpoints)
- `JARVIS_APP_AUTH_CACHE_TTL_SECONDS`: Cache TTL for successful auth validations (default: 60)

## Authentication

The OCR service uses **Jarvis Auth app-to-app authentication**. All protected endpoints require:

- `X-Jarvis-App-Id`: App identifier
- `X-Jarvis-App-Key`: App secret (API key)

**Public endpoints** (no auth required):
- `GET /health`

**Protected endpoints** (auth required):
- `POST /v1/ocr`
- `GET /v1/providers`

### Example Request with Auth

```bash
curl -H "X-Jarvis-App-Id: jarvis-recipes-server" \
     -H "X-Jarvis-App-Key: $JARVIS_APP_KEY" \
     -X POST http://localhost:5009/v1/ocr \
     -H "Content-Type: application/json" \
     -d '{"image": {"content_type": "image/png", "base64": "..."}}'
```

## API Endpoints

### `POST /v1/ocr`

Perform OCR on an image.

**Request:**
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

**Response:**
```json
{
  "provider_used": "tesseract",
  "text": "Extracted text...",
  "blocks": [
    {
      "text": "Example",
      "bbox": [10, 20, 100, 30],
      "confidence": 0.94
    }
  ],
  "meta": {
    "duration_ms": 123.45
  }
}
```

### `GET /v1/providers`

Get available OCR providers.

**Response:**
```json
{
  "providers": {
    "tesseract": true,
    "easyocr": false,
    "paddleocr": false,
    "apple_vision": false
  }
}
```

### `GET /health`

Health check endpoint.

**Response:**
```json
{
  "status": "ok"
}
```

## Development

**With Poetry (recommended):**
```bash
# Install dependencies
poetry install

# Run with auto-reload
poetry run uvicorn app.main:app --reload --port 5009
```

**With pip:**
```bash
# Install dependencies
pip install -r requirements.txt

# Run with auto-reload
uvicorn app.main:app --reload --port 5009
```

## Deployment

For native macOS deployment, use the provided deployment script:

```bash
# Deploy latest changes
./deploy.sh

# Start services
./run.sh --enable-redis-queue        # Service
./run-worker.sh                      # Worker
```

The deployment script handles:
- Git pull (latest code)
- Poetry dependency updates
- Graceful service shutdown

For detailed deployment options (launchd, PM2, screen/tmux), see [DEPLOYMENT.md](./DEPLOYMENT.md).

## Notes

- Apple Vision requires macOS and cannot run in Docker
- The service will fail fast at startup if Apple Vision is enabled in Docker
- Tesseract is always available as a fallback provider

