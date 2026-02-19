"""FastAPI application for Jarvis OCR Service."""

import logging
import os
import sys
from contextlib import asynccontextmanager
from typing import Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.responses import JSONResponse

# Note: .env is loaded in app.config before config is initialized
from app import service_config
from app.config import config
from app.models import (
    OCRRequest, OCRResponse, OCRBatchRequest, OCRBatchResponse,
    ProvidersResponse, HealthResponse, TextBlock,
    OCRJobResponse, OCRJobStatusResponse
)
from app.provider_manager import ProviderManager
from app.exceptions import OCRProcessingException, ProviderUnavailableException
from app.auth import verify_app_auth
from app.queue_client import queue_client
from app.services.settings_service import get_settings_service
from jarvis_settings_client import create_combined_auth, create_settings_router, create_superuser_auth

# Configure logging
logging.basicConfig(
    level=getattr(logging, config.OCR_LOG_LEVEL),
    format='{"timestamp": "%(asctime)s", "level": "%(levelname)s", "name": "%(name)s", "message": "%(message)s"}',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Global provider manager
provider_manager: Optional[ProviderManager] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup/shutdown."""
    global provider_manager
    
    # Startup
    logger.info("Starting Jarvis OCR Service...")

    # Initialize service discovery
    if service_config.init():
        logger.info("Service discovery initialized")
    else:
        logger.info("Using environment variables for service URLs")

    # Validate configuration
    try:
        config.validate()
        logger.info("Configuration validated")
    except Exception as e:
        logger.error(f"Configuration validation failed: {e}")
        sys.exit(1)
    
    # Initialize provider manager
    try:
        provider_manager = ProviderManager()
        available = provider_manager.get_available_providers()
        logger.info(f"Initialized providers: {available}")
    except Exception as e:
        logger.error(f"Failed to initialize providers: {e}")
        sys.exit(1)
    
    # Initialize auth cache
    from app.auth_cache import AuthCache, set_auth_cache
    auth_cache_instance = AuthCache(
        success_ttl=config.JARVIS_APP_AUTH_CACHE_TTL_SECONDS,
        failure_ttl=10  # 10 seconds for failures
    )
    set_auth_cache(auth_cache_instance)
    logger.info(f"Initialized auth cache (success TTL: {config.JARVIS_APP_AUTH_CACHE_TTL_SECONDS}s)")
    
    yield
    
    # Shutdown
    logger.info("Shutting down Jarvis OCR Service...")


# Create FastAPI app
app = FastAPI(
    title="Jarvis OCR Service",
    description="OCR microservice with pluggable backends",
    version="1.0.0",
    lifespan=lifespan
)

_auth_url = os.getenv("JARVIS_AUTH_BASE_URL", "http://localhost:7701")
_settings_router = create_settings_router(
    service=get_settings_service(),
    auth_dependency=create_combined_auth(_auth_url),
    write_auth_dependency=create_superuser_auth(_auth_url),
)
app.include_router(_settings_router, prefix="/settings", tags=["settings"])


@app.get("/health", response_model=HealthResponse)
async def health():
    """Health check endpoint."""
    return HealthResponse(status="ok")


@app.get("/v1/queue/status")
async def get_queue_status(_: dict = Depends(verify_app_auth)):
    """Get Redis queue status and statistics."""
    status = queue_client.get_status()
    
    if not status.get("redis_connected"):
        raise HTTPException(
            status_code=503,
            detail=status.get("error", "Redis queue is not available")
        )
    
    return status


@app.get("/v1/providers", response_model=ProvidersResponse)
async def get_providers(_: dict = Depends(verify_app_auth)):
    """Get available OCR providers."""
    if provider_manager is None:
        raise HTTPException(status_code=503, detail="Service not initialized")
    
    available = provider_manager.get_available_providers()
    return ProvidersResponse(providers=available)


@app.post("/v1/ocr", response_model=OCRJobResponse)
async def ocr(request: OCRRequest, http_request: Request, _: dict = Depends(verify_app_auth)):
    """Queue an OCR job for processing."""
    if provider_manager is None:
        raise HTTPException(status_code=503, detail="Service not initialized")
    
    # Extract correlation ID if present
    correlation_id = http_request.headers.get("X-Correlation-ID", "unknown")
    logger.info(f"OCR job request received [correlation_id={correlation_id}, provider={request.provider}]")
    
    try:
        # Prepare job data
        job_data = {
            "document_id": request.document_id,
            "provider": request.provider,
            "image": {
                "content_type": request.image.content_type,
                "base64": request.image.base64
            },
            "options": {
                "language_hints": request.options.language_hints if request.options else None,
                "return_boxes": request.options.return_boxes if request.options else True,
                "mode": request.options.mode if request.options else "document"
            },
            "correlation_id": correlation_id
        }
        
        # Enqueue job
        job_id = queue_client.enqueue_job(job_data)
        
        # Get job status to return created_at
        job_status = queue_client.get_job_status(job_id)
        
        return OCRJobResponse(
            job_id=job_id,
            status=job_status.get("status", "pending") if job_status else "pending",
            created_at=job_status.get("created_at", "") if job_status else ""
        )
    
    except RuntimeError as e:
        # Redis unavailable or queue error
        logger.error(f"Failed to queue job [correlation_id={correlation_id}]: {e}")
        raise HTTPException(status_code=503, detail=f"Queue service unavailable: {str(e)}")
    
    except Exception as e:
        # Internal error
        logger.error(f"Internal error [correlation_id={correlation_id}]: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@app.get("/v1/ocr/jobs/{job_id}", response_model=OCRJobStatusResponse)
async def get_job_status(job_id: str, _: dict = Depends(verify_app_auth)):
    """Get OCR job status and results."""
    try:
        job_status = queue_client.get_job_status(job_id)
        
        if job_status is None:
            raise HTTPException(status_code=404, detail="Job not found")
        
        # Convert result to OCRResponse if present
        result = None
        if "result" in job_status and job_status["result"]:
            result_data = job_status["result"]
            result = OCRResponse(
                provider_used=result_data.get("provider_used", ""),
                text=result_data.get("text", ""),
                blocks=[
                    TextBlock(
                        text=block["text"],
                        bbox=block["bbox"],
                        confidence=block["confidence"]
                    )
                    for block in result_data.get("blocks", [])
                ],
                meta=result_data.get("meta", {})
            )
        
        return OCRJobStatusResponse(
            job_id=job_status.get("job_id", job_id),
            status=job_status.get("status", "unknown"),
            created_at=job_status.get("created_at", ""),
            updated_at=job_status.get("updated_at"),
            result=result,
            error=job_status.get("error")
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting job status: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@app.post("/v1/ocr/batch", response_model=OCRBatchResponse)
async def ocr_batch(request: OCRBatchRequest, http_request: Request, _: dict = Depends(verify_app_auth)):
    """Perform OCR on multiple images."""
    if provider_manager is None:
        raise HTTPException(status_code=503, detail="Service not initialized")
    
    # Extract correlation ID if present
    correlation_id = http_request.headers.get("X-Correlation-ID", "unknown")
    logger.info(f"Batch OCR request received [correlation_id={correlation_id}, provider={request.provider}, images={len(request.images)}]")
    
    try:
        # Extract base64 images and content types
        images_base64 = [img.base64 for img in request.images]
        content_types = [img.content_type for img in request.images]
        
        # Process batch
        results, provider_used = await provider_manager.process_batch(
            images_base64=images_base64,
            content_types=content_types,
            provider_name=request.provider,
            language_hints=request.options.language_hints if request.options else None,
            return_boxes=request.options.return_boxes if request.options else True,
            mode=request.options.mode if request.options else "document"
        )
        
        # Convert results to response format
        response_results = []
        total_duration = 0.0
        
        for result in results:
            blocks = [
                TextBlock(
                    text=block.text,
                    bbox=block.bbox,
                    confidence=block.confidence
                )
                for block in result.blocks
            ]
            
            response_results.append(OCRResponse(
                provider_used=provider_used,
                text=result.text,
                blocks=blocks,
                meta={
                    "duration_ms": round(result.duration_ms, 2)
                }
            ))
            
            total_duration += result.duration_ms
        
        return OCRBatchResponse(
            results=response_results,
            meta={
                "total_images": len(results),
                "total_duration_ms": round(total_duration, 2),
                "provider_used": provider_used
            }
        )
    
    except ProviderUnavailableException as e:
        logger.warning(f"Provider unavailable [correlation_id={correlation_id}]: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    
    except OCRProcessingException as e:
        logger.warning(f"OCR processing failed [correlation_id={correlation_id}]: {e}")
        raise HTTPException(status_code=422, detail=str(e))
    
    except ValueError as e:
        logger.warning(f"Bad request [correlation_id={correlation_id}]: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    
    except Exception as e:
        logger.error(f"Internal error [correlation_id={correlation_id}]: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Global exception handler."""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"}
    )


if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=config.OCR_PORT,
        log_level=config.OCR_LOG_LEVEL.lower()
    )

