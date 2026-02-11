# Work In Progress

## Async LLM Validation Flow

Adding an async validation pipeline where OCR results are validated by an LLM before being returned. This enables a tiered fallback strategy: if one OCR provider produces invalid output, the system automatically retries with the next tier.

### How it works

1. OCR is performed on an image using the first enabled tier (e.g., `apple_vision`)
2. The extracted text is sent to `jarvis-llm-proxy-api` for validation via a queue job
3. The OCR service saves the pending state to Redis and waits for a callback
4. When the LLM proxy completes validation, it POSTs back to `/internal/validation/callback`
5. If valid: the result is recorded and the next image (if batch) is processed
6. If invalid: the next tier is tried (e.g., `tesseract`), repeating from step 2
7. Once all images are processed, a completion message is sent to the reply queue

### New files

| File | Purpose |
|------|---------|
| `app/validation_state.py` | `PendingValidationState` dataclass + `ValidationStateManager` (Redis-backed state storage) |
| `app/validation_callback.py` | FastAPI router for `/internal/validation/callback` endpoint, parses LLM results |
| `app/llm_queue_client.py` | Client for enqueueing validation jobs to `jarvis-llm-proxy-api` |
| `app/continue_processing.py` | Continuation logic after validation — tier fallback, multi-image progression, completion |
| `tests/test_validation_state.py` | Tests for validation state serialization and Redis operations |
| `tests/test_validation_callback.py` | Tests for callback endpoint and result parsing |
| `tests/test_llm_queue_client.py` | Tests for LLM queue client payload building and enqueue |
| `tests/test_continue_processing.py` | Tests for post-validation continuation logic |
| `tests/test_async_flow_integration.py` | Integration tests for the full async validation flow |

### Other changes

- `app/main.py`: Added `create_superuser_auth` for write-protected settings, moved settings route to `/settings`
- `Dockerfile`: Fixed `libgl1-mesa-glx` (removed in Debian Trixie) → `libgl1`, added `git` for pip git dependencies
- `docker-compose.{dev,prod}.yaml`: Removed local Redis container (app uses remote Redis on Linux host)

### Still TODO

- Wire the validation callback router into `app/main.py`
- End-to-end testing of the full async flow with live services
- Error handling for Redis connection failures during callback
