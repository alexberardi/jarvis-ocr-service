"""Client for validating app credentials with Jarvis Auth."""

import logging
from typing import Optional, Dict, Any
import httpx

from app.config import config

logger = logging.getLogger(__name__)


class AuthClient:
    """Client for validating app credentials with Jarvis Auth."""
    
    def __init__(self):
        self.timeout = 5.0  # 5 second timeout for auth calls
    
    @property
    def base_url(self) -> str:
        """Get base URL from config (read dynamically)."""
        return config.JARVIS_AUTH_BASE_URL
    
    async def verify_app_credentials(
        self,
        app_id: str,
        app_key: str
    ) -> Dict[str, Any]:
        """
        Verify app credentials with Jarvis Auth.
        
        Args:
            app_id: App identifier from X-Jarvis-App-Id header
            app_key: App secret from X-Jarvis-App-Key header
        
        Returns:
            Dict with validation result:
            - On success (200): {"app_id": "...", "name": "..."}
            - On failure: {"ok": False, "error_code": "...", "error_message": "..."}
        
        Raises:
            httpx.RequestError: If the request to auth service fails
        """
        base_url = self.base_url
        if not base_url:
            raise ValueError("JARVIS_AUTH_BASE_URL is not configured")
        
        url = f"{base_url.rstrip('/')}/internal/app-ping"
        
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    url,
                    headers={
                        "X-Jarvis-App-Id": app_id,
                        "X-Jarvis-App-Key": app_key
                    }
                )
                
                # Check if response indicates success
                if response.status_code == 200:
                    # Parse response
                    try:
                        data = response.json()
                        # Return the response data (contains app_id, name, etc.)
                        return data
                    except Exception:
                        # If response is not JSON, treat as error
                        logger.warning(f"Auth service returned non-JSON response: {response.status_code}")
                        return {
                            "ok": False,
                            "error_code": "invalid_response",
                            "error_message": "Auth service returned invalid response"
                        }
                else:
                    # Auth service says credentials are invalid
                    try:
                        data = response.json()
                        return {
                            "ok": False,
                            "error_code": data.get("error_code", "invalid_app_credentials"),
                            "error_message": data.get("error_message", "Invalid app credentials")
                        }
                    except Exception:
                        return {
                            "ok": False,
                            "error_code": "invalid_app_credentials",
                            "error_message": f"Auth service returned status {response.status_code}"
                        }
        
        except httpx.TimeoutException:
            logger.error("Auth service request timed out")
            raise httpx.RequestError("Auth service timeout")
        
        except httpx.RequestError as e:
            logger.error(f"Failed to reach auth service: {e}")
            raise


# Global auth client instance
auth_client = AuthClient()

