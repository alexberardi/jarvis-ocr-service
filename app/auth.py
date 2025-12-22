"""FastAPI dependency for app-to-app authentication."""

import logging
from typing import Optional
from fastapi import Header, HTTPException, Request
import httpx

from app.config import config
from app.auth_client import auth_client
from app.auth_cache import get_auth_cache

logger = logging.getLogger(__name__)


async def verify_app_auth(
    request: Request,
    x_jarvis_app_id: Optional[str] = Header(None, alias="X-Jarvis-App-Id"),
    x_jarvis_app_key: Optional[str] = Header(None, alias="X-Jarvis-App-Key")
) -> dict:
    """
    FastAPI dependency to verify app-to-app authentication.
    
    Checks X-Jarvis-App-Id and X-Jarvis-App-Key headers and validates
    them with Jarvis Auth service.
    
    Returns:
        Dict with app info if valid
    
    Raises:
        HTTPException: 401 if missing/invalid, 503 if auth service unavailable
    """
    # Check if headers are present
    if not x_jarvis_app_id or not x_jarvis_app_key:
        logger.warning("Missing app auth headers")
        raise HTTPException(
            status_code=401,
            detail={
                "error_code": "unauthorized",
                "error_message": "Missing or invalid app credentials"
            }
        )
    
    # Check cache first
    cache = get_auth_cache()
    cached_result = cache.get(x_jarvis_app_id, x_jarvis_app_key)
    if cached_result is not None:
        # Success response has "app_id" key, failure has "ok": False
        if "app_id" in cached_result:
            logger.debug(f"Using cached auth result for app: {x_jarvis_app_id}")
            return cached_result
        else:
            # Cached failure - reject
            logger.debug(f"Using cached failure for app: {x_jarvis_app_id}")
            raise HTTPException(
                status_code=401,
                detail={
                    "error_code": "unauthorized",
                    "error_message": "Missing or invalid app credentials"
                }
            )
    
    # Not in cache, validate with auth service
    try:
        result = await auth_client.verify_app_credentials(
            app_id=x_jarvis_app_id,
            app_key=x_jarvis_app_key
        )
        
        # Cache the result
        cache = get_auth_cache()
        cache.set(x_jarvis_app_id, x_jarvis_app_key, result)
        
        # Success response has "app_id" key, failure has "ok": False
        if "app_id" in result:
            logger.info(f"App authenticated: {x_jarvis_app_id}")
            return result
        else:
            # Invalid credentials
            error_code = result.get("error_code", "invalid_app_credentials")
            error_message = result.get("error_message", "Invalid app credentials")
            logger.warning(f"App authentication failed: {x_jarvis_app_id} - {error_code}")
            raise HTTPException(
                status_code=401,
                detail={
                    "error_code": "unauthorized",
                    "error_message": "Missing or invalid app credentials"
                }
            )
    
    except httpx.RequestError as e:
        # Auth service is unavailable
        logger.error(f"Auth service unavailable: {e}")
        print()
        raise HTTPException(
            status_code=503,
            detail={
                "error_code": "auth_unavailable",
                "error_message": "Auth service unavailable"
            }
        )
    
    except Exception as e:
        # Unexpected error
        logger.error(f"Unexpected auth error: {e}", exc_info=True)
        raise HTTPException(
            status_code=503,
            detail={
                "error_code": "auth_unavailable",
                "error_message": "Auth service unavailable"
            }
        )

