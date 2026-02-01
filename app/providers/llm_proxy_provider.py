"""LLM Proxy OCR provider implementation (Vision and Cloud models)."""

import asyncio
import base64
import io
import logging
import time
from typing import List, Optional, Tuple

import httpx
from PIL import Image

from app import service_config
from app.config import config
from app.providers.base import OCRProvider, OCRResult, TextBlock

logger = logging.getLogger(__name__)


def run_async(coro):
    """
    Run an async coroutine from a synchronous context.
    Works whether we're in an async event loop or not.
    """
    try:
        # Try to get the running event loop
        loop = asyncio.get_running_loop()
        # We're in an async context (FastAPI), but can't use run_until_complete
        # from within a running coroutine. Use a new thread with a new event loop.
        import concurrent.futures
        import threading
        
        result = None
        exception = None
        
        def run_in_thread():
            nonlocal result, exception
            try:
                new_loop = asyncio.new_event_loop()
                asyncio.set_event_loop(new_loop)
                result = new_loop.run_until_complete(coro)
                new_loop.close()
            except Exception as e:
                exception = e
        
        thread = threading.Thread(target=run_in_thread)
        thread.start()
        thread.join()
        
        if exception:
            raise exception
        return result
    except RuntimeError:
        # No running loop, create a new one
        return asyncio.run(coro)


class LLMProxyProvider(OCRProvider):
    """Base class for LLM Proxy providers (Vision and Cloud)."""
    
    def __init__(self, model_name: str):
        """
        Initialize LLM Proxy provider.

        Args:
            model_name: Model name to use ("vision" or "cloud")
        """
        self.model_name = model_name
        self.app_id = config.JARVIS_APP_ID
        self.app_key = config.JARVIS_APP_KEY
        self.timeout = 60.0  # 60 second timeout for LLM calls

    @property
    def base_url(self) -> str:
        """Get LLM Proxy URL from service discovery (read dynamically)."""
        return service_config.get_llm_proxy_url()
    
    @property
    def name(self) -> str:
        return f"llm_proxy_{self.model_name}"
    
    def is_available(self) -> bool:
        """Check if LLM Proxy is available."""
        if not self.base_url or not self.app_id or not self.app_key:
            return False
        return True
    
    def _create_image_message(self, image_bytes: bytes, content_type: str) -> dict:
        """Create an image message for the LLM API."""
        # Convert image to base64 data URI
        image_base64 = base64.b64encode(image_bytes).decode('utf-8')
        data_uri = f"data:{content_type};base64,{image_base64}"
        
        return {
            "type": "image_url",
            "image_url": {
                "url": data_uri
            }
        }
    
    async def _call_llm_proxy(
        self,
        messages: List[dict],
        response_format: Optional[dict] = None,
        single_image: bool = False
    ) -> str:
        """
        Call the LLM Proxy API (async).
        
        Args:
            messages: List of message objects for OpenAI-compatible API
            response_format: Optional response format (e.g., {"type": "json_object"})
            single_image: If True, process one image at a time (for vision model)
        
        Returns:
            Extracted text from LLM response
        """
        if not self.base_url:
            raise RuntimeError("JARVIS_LLM_PROXY_URL is not configured")
        
        url = f"{self.base_url.rstrip('/')}/v1/chat/completions"
        
        request_body = {
            "model": self.model_name,
            "messages": messages,
            "max_tokens": 4096  # Adjust as needed
        }
        
        if response_format:
            request_body["response_format"] = response_format
        
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    url,
                    json=request_body,
                    headers={
                        "Content-Type": "application/json",
                        "X-Jarvis-App-Id": self.app_id,
                        "X-Jarvis-App-Key": self.app_key
                    }
                )
                
                response.raise_for_status()
                data = response.json()
                
                # Extract text from OpenAI-compatible response
                if "choices" in data and len(data["choices"]) > 0:
                    content = data["choices"][0]["message"]["content"]
                    return content.strip()
                else:
                    raise RuntimeError("Invalid response format from LLM proxy")
        
        except httpx.TimeoutException:
            raise RuntimeError("LLM proxy request timed out")
        except httpx.RequestError as e:
            raise RuntimeError(f"Failed to reach LLM proxy: {e}")
    
    async def _validate_ocr_output(self, text: str) -> bool:
        """
        Validate OCR output using LLM proxy to detect garbled/nonsense text.
        
        Args:
            text: OCR extracted text to validate
        
        Returns:
            True if text appears valid, False if garbled/nonsense
        """
        if not text or len(text.strip()) < 3:  # Too short to be meaningful
            return False
        
        if not self.base_url:
            return True  # Can't validate, assume valid
        
        # Use "full" model for validation
        url = f"{self.base_url.rstrip('/')}/v1/chat/completions"
        
        prompt = f"""Analyze this OCR-extracted text and determine if it contains valid, readable content or if it's garbled nonsense.

Text to analyze:
{text[:500]}  # Limit to first 500 chars

Respond with JSON:
{{
  "is_valid": true/false,
  "confidence": 0.0-1.0,
  "reason": "brief explanation"
}}"""
        
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    url,
                    json={
                        "model": "full",
                        "messages": [
                            {
                                "role": "user",
                                "content": prompt
                            }
                        ],
                        "response_format": {"type": "json_object"},
                        "max_tokens": 200
                    },
                    headers={
                        "Content-Type": "application/json",
                        "X-Jarvis-App-Id": self.app_id,
                        "X-Jarvis-App-Key": self.app_key
                    }
                )
                
                response.raise_for_status()
                data = response.json()
                
                if "choices" in data and len(data["choices"]) > 0:
                    content = data["choices"][0]["message"]["content"]
                    import json
                    validation = json.loads(content)
                    return validation.get("is_valid", True)  # Default to valid if unclear
                else:
                    return True  # Can't validate, assume valid
        
        except Exception as e:
            logger.warning(f"OCR validation failed: {e}, assuming valid")
            return True  # On error, assume valid to avoid false negatives
    
    def process(
        self,
        image_bytes: bytes,
        language_hints: Optional[List[str]] = None,
        return_boxes: bool = True,
        mode: str = "document"
    ) -> OCRResult:
        """Process image with LLM Proxy (single image)."""
        start = time.time()
        
        # Create prompt with JSON schema specification
        prompt = """OCR this image and extract all text. Return the result as JSON in this exact format:
{
  "page1": {
    "text": "extracted text here"
  }
}

The text field should contain all readable text from the image. If the image contains no text, return an empty string."""
        
        if language_hints:
            languages = ", ".join(language_hints)
            prompt += f" The text may be in: {languages}."
        
        # Create message with image
        image_message = self._create_image_message(image_bytes, "image/png")
        
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    image_message
                ]
            }
        ]
        
        # Call LLM proxy with JSON response format
        import json
        response_text = run_async(self._call_llm_proxy(
            messages, 
            response_format={"type": "json_object"},
            single_image=True
        ))
        
        # Parse JSON response
        try:
            response_json = json.loads(response_text)
            text = response_json.get("page1", {}).get("text", "")
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"Failed to parse LLM JSON response: {e}, using raw text")
            text = response_text  # Fallback to raw text
        
        # Validate OCR output
        is_valid = run_async(self._validate_ocr_output(text))
        if not is_valid:
            logger.warning(f"OCR output appears to be garbled/nonsense: {text[:100]}")
            # Still return it, but caller can check if needed
        
        # For LLM providers, we don't get bounding boxes
        blocks = []
        if return_boxes:
            # Create a single block with the full text
            # We don't have actual bbox data from LLM
            image = Image.open(io.BytesIO(image_bytes))
            blocks.append(TextBlock(
                text=text,
                bbox=[0.0, 0.0, float(image.width), float(image.height)],
                confidence=0.95  # LLM confidence is generally high
            ))
        
        duration_ms = (time.time() - start) * 1000
        
        return OCRResult(
            text=text,
            blocks=blocks,
            duration_ms=duration_ms
        )


class LLMProxyVisionProvider(LLMProxyProvider):
    """LLM Proxy provider using Vision model (processes images one at a time)."""
    
    def __init__(self):
        super().__init__("vision")
    
    def process_batch(
        self,
        images: List[Tuple[bytes, str]],  # List of (image_bytes, content_type)
        language_hints: Optional[List[str]] = None,
        return_boxes: bool = True,
        mode: str = "document"
    ) -> List[OCRResult]:
        """
        Process multiple images (Vision model processes one at a time).
        
        Args:
            images: List of (image_bytes, content_type) tuples
            language_hints: Optional language hints
            return_boxes: Whether to return bounding boxes
            mode: OCR mode
        
        Returns:
            List of OCRResult, one per image
        """
        results = []
        
        for image_bytes, content_type in images:
            result = self.process(
                image_bytes=image_bytes,
                language_hints=language_hints,
                return_boxes=return_boxes,
                mode=mode
            )
            results.append(result)
        
        return results


class LLMProxyCloudProvider(LLMProxyProvider):
    """LLM Proxy provider using Cloud model (can process multiple images at once)."""
    
    def __init__(self):
        super().__init__("cloud")
    
    def process_batch(
        self,
        images: List[Tuple[bytes, str]],  # List of (image_bytes, content_type)
        language_hints: Optional[List[str]] = None,
        return_boxes: bool = True,
        mode: str = "document"
    ) -> List[OCRResult]:
        """
        Process multiple images (Cloud model processes all at once).
        Each image is sent as a separate message in the content array.
        
        Args:
            images: List of (image_bytes, content_type) tuples
            language_hints: Optional language hints
            return_boxes: Whether to return bounding boxes
            mode: OCR mode
        
        Returns:
            List of OCRResult, one per image
        """
        start = time.time()
        
        # Create prompt with JSON schema specification
        page_keys = ", ".join([f"page{i+1}" for i in range(len(images))])
        prompt = f"""OCR these {len(images)} images and extract all text from each. Return the result as JSON in this exact format:
{{
  "page1": {{
    "text": "extracted text from first image"
  }},
  "page2": {{
    "text": "extracted text from second image"
  }},
  ...
  "page{len(images)}": {{
    "text": "extracted text from last image"
  }}
}}

Each text field should contain all readable text from the corresponding image. If an image contains no text, return an empty string for that page."""
        
        if language_hints:
            languages = ", ".join(language_hints)
            prompt += f" The text may be in: {languages}."
        
        # Create message with each image as a separate message in content array
        content = [{"type": "text", "text": prompt}]
        for image_bytes, content_type in images:
            image_message = self._create_image_message(image_bytes, content_type)
            content.append(image_message)
        
        messages = [
            {
                "role": "user",
                "content": content
            }
        ]
        
        # Call LLM proxy with all images and JSON response format
        import json
        response_text = run_async(self._call_llm_proxy(
            messages,
            response_format={"type": "json_object"},
            single_image=False
        ))
        
        # Parse JSON response
        try:
            response_json = json.loads(response_text)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse LLM JSON response: {e}")
            # Fallback: create empty results
            response_json = {}
        
        # Create results for each image
        results = []
        for i, (image_bytes, content_type) in enumerate(images):
            page_key = f"page{i+1}"
            text = response_json.get(page_key, {}).get("text", "")
            
            # Validate OCR output
            is_valid = run_async(self._validate_ocr_output(text))
            if not is_valid:
                logger.warning(f"OCR output for page {i+1} appears garbled: {text[:100]}")
            
            blocks = []
            if return_boxes:
                image = Image.open(io.BytesIO(image_bytes))
                blocks.append(TextBlock(
                    text=text,
                    bbox=[0.0, 0.0, float(image.width), float(image.height)],
                    confidence=0.95
                ))
            
            # Estimate duration per image (total / count)
            duration_ms = ((time.time() - start) * 1000) / len(images)
            
            results.append(OCRResult(
                text=text,
                blocks=blocks,
                duration_ms=duration_ms
            ))
        
        return results

