

# Jarvis OCR Server — App-to-App Authentication

This document specifies how **clients (other Jarvis services)** must authenticate to the **Jarvis OCR Server**.

The OCR server uses **Jarvis Auth app-to-app authentication** (shared app id/key headers). The OCR server itself is the *resource server*; callers present app credentials on every request.

## Overview

### Who calls the OCR server?
Typical internal callers:
- `jarvis-recipes-server`
- `jarvis-command-center`
- `jarvis-llm-proxy` (only if you choose to route OCR through it later)

### How is authentication performed?
Callers must send two headers:
- `X-Jarvis-App-Id`
- `X-Jarvis-App-Key`

The OCR server validates these headers by calling **Jarvis Auth**.

### What does the OCR server do with the headers?
1. Extract `X-Jarvis-App-Id` and `X-Jarvis-App-Key` from the request.
2. Call Jarvis Auth to verify them.
3. If valid: process the request.
4. If invalid/missing: reject.

## Required Request Headers

All protected routes **MUST** include:

| Header | Required | Description |
|---|---:|---|
| `X-Jarvis-App-Id` | ✅ | App identifier issued by Jarvis Auth |
| `X-Jarvis-App-Key` | ✅ | App secret (API key) issued by Jarvis Auth |

### Header example

```http
X-Jarvis-App-Id: jarvis-recipes-server
X-Jarvis-App-Key: <secret>
```

## Validation Strategy (Centralized)

### Validation endpoint
The OCR server validates app credentials by making a server-to-server call to Jarvis Auth.

- **Jarvis Auth Base URL:** `JARVIS_AUTH_BASE_URL` (env var)
- **Verification route:** `POST /internal/app-ping` *(exact path should match jarvis-auth implementation)*

#### OCR → Auth request

```http
GET /internal/app-ping HTTP/1.1
Host: auth
X-Jarvis-App-Id: <from X-Jarvis-App-Id>
X-Jarvis-App-Key: <from X-Jarvis-App-Key>
```

#### Auth → OCR response (success)

```json
{
  "ok": true,
  "app_id": "jarvis-recipes-server",
  "scopes": ["ocr:read", "ocr:write"],
  "expires_at": null
}
```

#### Auth → OCR response (failure)

```json
{
  "ok": false,
  "error_code": "invalid_app_credentials",
  "error_message": "Invalid app id/key"
}
```

> Note: The exact response fields may differ depending on the jarvis-auth implementation. The OCR server must treat **any non-2xx response** or **ok=false** as authentication failure.

## Recommended Server Enforcement

### Protected routes
All OCR endpoints that do real work (upload, ingest, OCR, parsing, results, etc.) must require app auth.

### Public routes
These routes **may remain unauthenticated**:
- `GET /health`

Optionally public (your call):
- `GET /metrics` (if used internally by monitoring; consider protecting if exposed externally)

### Rejection behavior
If missing or invalid:
- Return `401 Unauthorized`
- Include a structured error response

Example:

```json
{
  "error_code": "unauthorized",
  "error_message": "Missing or invalid app credentials"
}
```

If Jarvis Auth is unreachable:
- Prefer `503 Service Unavailable`

```json
{
  "error_code": "auth_unavailable",
  "error_message": "Auth service unavailable"
}
```

## Caching / Traffic Reduction

Unlike end-user auth, app-to-app validation is typically lightweight, but we still want to avoid unnecessary traffic.

### Recommended caching approach
- Cache the **(app_id, app_key) → ok** result in-memory with a TTL.
- Default TTL: **60 seconds** (configurable).

Suggested env var:
- `JARVIS_APP_AUTH_CACHE_TTL_SECONDS` (default `60`)

Behavior:
- Cache **successes** (ok=true).
- Cache **failures** briefly (e.g., 5–15 seconds) to prevent repeated bad calls during misconfig.

> If you want maximum security and have low traffic, you can disable caching by setting TTL to `0`.

## Credential Rotation

Callers should assume app keys can rotate.

Recommendations:
- Keys should be rotated via Jarvis Auth admin tooling.
- OCR server should validate on every request (with short TTL caching allowed).
- If a key rotates, callers must update their secret store and redeploy.

## Client Integration Examples

### Example: Python (httpx)

```python
import httpx

headers = {
  "X-Jarvis-App-Id": "jarvis-recipes-server",
  "X-Jarvis-App-Key": "...",
}

resp = httpx.get("https://ocr-staging.jarvisautomation.io/health", headers=headers, timeout=10)
print(resp.status_code, resp.text)
```

### Example: curl

```bash
curl -H "X-Jarvis-App-Id: jarvis-recipes-server" \
     -H "X-Jarvis-App-Key: $JARVIS_APP_KEY" \
     https://ocr-staging.jarvisautomation.io/health
```

## Security Notes

- App keys are secrets. **Never** log them.
- Do not include secrets in error responses.
- All traffic should be over TLS.
- Prefer private networking where possible (e.g., internal network, tunnel).

## Implementation Checklist

- [ ] Add a FastAPI dependency or middleware that enforces app auth on protected routes.
- [ ] Implement Auth verification call to Jarvis Auth.
- [ ] Add TTL cache (configurable) for successful validations.
- [ ] Ensure `/health` stays unauthenticated.
- [ ] Add tests: missing headers → 401, invalid → 401, auth down → 503.

---