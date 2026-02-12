"""Image reference resolver for different image sources."""

import os
import logging
import urllib.parse
from typing import Tuple
from pathlib import Path

# Required dependencies for S3/minio/HTTPS support
import boto3
from botocore.exceptions import ClientError, NoCredentialsError
from botocore.client import Config
import requests

from app.config import config

logger = logging.getLogger(__name__)


class ImageResolverError(Exception):
    """Raised when an image cannot be resolved."""
    pass


def resolve_image(image_ref: dict) -> Tuple[bytes, str]:
    """
    Resolve an image reference to image bytes and content type.
    
    Args:
        image_ref: Dict with 'kind' and 'value' keys
    
    Returns:
        Tuple of (image_bytes, content_type)
    
    Raises:
        ImageResolverError: If image cannot be resolved
    """
    kind = image_ref.get("kind")
    value = image_ref.get("value")
    
    if not kind or not value:
        raise ImageResolverError("image_ref must have 'kind' and 'value' fields")
    
    # Check for PDF rejection (before resolving)
    if value.lower().endswith('.pdf'):
        raise ImageResolverError("PDF files are not supported in v1 (error code: unsupported_media)")
    
    if kind == "local_path":
        return _resolve_local_path(value)
    elif kind == "s3":
        return _resolve_s3(value)
    elif kind == "minio":
        return _resolve_minio(value)
    elif kind == "db":
        raise ImageResolverError("Image kind 'db' is not yet supported in v1")
    else:
        raise ImageResolverError(f"Unknown image kind: {kind}")


def _resolve_local_path(path: str) -> Tuple[bytes, str]:
    """
    Resolve a local file path to image bytes.
    Uses /data/images/ as the in-container mount root per PRD.
    
    Args:
        path: Local file system path (relative to /data/images/ or absolute)
    
    Returns:
        Tuple of (image_bytes, content_type)
    
    Raises:
        ImageResolverError: If file cannot be read
    """
    try:
        # If path is relative, prepend /data/images/ (container mount root)
        if not os.path.isabs(path):
            resolved_path = Path("/data/images") / path
        else:
            resolved_path = Path(path)
        
        resolved_path = resolved_path.resolve()
        
        # Check if file exists
        if not resolved_path.exists():
            raise ImageResolverError(f"Image file not found: {path}")
        
        # Check if it's a file (not directory)
        if not resolved_path.is_file():
            raise ImageResolverError(f"Path is not a file: {path}")
        
        # Read file
        with open(resolved_path, "rb") as f:
            image_bytes = f.read()
        
        # Determine content type from extension
        ext = resolved_path.suffix.lower()
        content_type_map = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif": "image/gif",
            ".bmp": "image/bmp",
            ".webp": "image/webp",
            ".tiff": "image/tiff",
            ".tif": "image/tiff"
        }
        
        content_type = content_type_map.get(ext, "image/png")  # Default to PNG
        
        logger.debug(f"Resolved local path: {path} -> {len(image_bytes)} bytes, {content_type}")
        return image_bytes, content_type
        
    except PermissionError:
        raise ImageResolverError(f"Permission denied reading image: {path}")
    except Exception as e:
        if isinstance(e, ImageResolverError):
            raise
        raise ImageResolverError(f"Failed to read image from {path}: {str(e)}")


def _resolve_s3(uri: str) -> Tuple[bytes, str]:
    """
    Resolve an S3 URI to image bytes.
    Supports s3://bucket/key or HTTPS URLs.
    
    Args:
        uri: S3 URI (s3://bucket/key) or HTTPS URL
    
    Returns:
        Tuple of (image_bytes, content_type)
    
    Raises:
        ImageResolverError: If image cannot be resolved
    """
    # Check if it's an HTTPS URL (could be S3 presigned URL)
    if uri.startswith("https://") or uri.startswith("http://"):
        return _resolve_https(uri)
    
    # Parse s3:// URI
    if not uri.startswith("s3://"):
        raise ImageResolverError(f"Invalid S3 URI format: {uri}")
    
    try:
        parsed = urllib.parse.urlparse(uri)
        bucket = parsed.netloc
        key = parsed.path.lstrip("/")
        
        if not bucket or not key:
            raise ImageResolverError(f"Invalid S3 URI: {uri}")
        
        # Create S3 client with optional custom endpoint (for MinIO)
        s3_config = {
            "region_name": config.S3_REGION
        }
        
        if config.S3_ENDPOINT_URL:
            s3_config["endpoint_url"] = config.S3_ENDPOINT_URL
        
        # Configure path-style addressing if needed (common for MinIO)
        if config.S3_FORCE_PATH_STYLE:
            s3_config["config"] = Config(signature_version='s3v4', s3={'addressing_style': 'path'})
        
        s3_client = boto3.client("s3", **s3_config)
        
        # Download object
        response = s3_client.get_object(Bucket=bucket, Key=key)
        image_bytes = response["Body"].read()
        
        # Get content type from response or infer from extension
        content_type = response.get("ContentType")
        if not content_type:
            content_type = _infer_content_type(key)
        
        logger.debug(f"Resolved S3 URI: {uri} -> {len(image_bytes)} bytes, {content_type}")
        return image_bytes, content_type
        
    except NoCredentialsError:
        raise ImageResolverError(f"No AWS credentials found for S3 access: {uri}")
    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code", "Unknown")
        if error_code == "NoSuchKey":
            raise ImageResolverError(f"S3 object not found: {uri}")
        elif error_code == "AccessDenied":
            raise ImageResolverError(f"Access denied to S3 object: {uri}")
        else:
            raise ImageResolverError(f"Failed to access S3 object {uri}: {error_code}")
    except Exception as e:
        if isinstance(e, ImageResolverError):
            raise
        raise ImageResolverError(f"Failed to resolve S3 URI {uri}: {str(e)}")


def _resolve_minio(uri: str) -> Tuple[bytes, str]:
    """
    Resolve a MinIO URI to image bytes.
    MinIO uses S3-compatible API, so we can use boto3 with custom endpoint.
    
    Args:
        uri: MinIO URI (s3://bucket/key or minio://bucket/key)
    
    Returns:
        Tuple of (image_bytes, content_type)
    
    Raises:
        ImageResolverError: If image cannot be resolved
    """
    # MinIO can use s3:// or minio:// prefix
    # Convert minio:// to s3:// (MinIO is S3-compatible)
    if uri.startswith("minio://"):
        uri = uri.replace("minio://", "s3://", 1)
    
    # Use S3 resolver (MinIO is S3-compatible)
    # Custom endpoint should be configured via S3_ENDPOINT_URL env var
    return _resolve_s3(uri)


def _resolve_https(url: str) -> Tuple[bytes, str]:
    """
    Resolve an HTTPS/HTTP URL to image bytes.
    
    Args:
        url: HTTPS or HTTP URL
    
    Returns:
        Tuple of (image_bytes, content_type)
    
    Raises:
        ImageResolverError: If image cannot be resolved
    """
    try:
        response = requests.get(url, timeout=30, stream=True)
        response.raise_for_status()
        
        image_bytes = response.content
        content_type = response.headers.get("Content-Type", "image/png")
        
        logger.debug(f"Resolved HTTPS URL: {url} -> {len(image_bytes)} bytes, {content_type}")
        return image_bytes, content_type
        
    except requests.exceptions.RequestException as e:
        raise ImageResolverError(f"Failed to fetch image from {url}: {str(e)}")
    except Exception as e:
        if isinstance(e, ImageResolverError):
            raise
        raise ImageResolverError(f"Failed to resolve HTTPS URL {url}: {str(e)}")


def _infer_content_type(path_or_key: str) -> str:
    """Infer content type from file extension."""
    ext = Path(path_or_key).suffix.lower()
    content_type_map = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".bmp": "image/bmp",
        ".webp": "image/webp",
        ".tiff": "image/tiff",
        ".tif": "image/tiff"
    }
    return content_type_map.get(ext, "image/png")

