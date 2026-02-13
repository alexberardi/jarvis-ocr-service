"""Settings definitions for jarvis-ocr-service.

Defines all configurable settings with their types, defaults, and metadata.
"""

from jarvis_settings_client import SettingDefinition


SETTINGS_DEFINITIONS: list[SettingDefinition] = [
    # Provider enable/disable flags
    SettingDefinition(
        key="ocr.enable_easyocr",
        category="ocr.providers",
        value_type="bool",
        default=False,
        description="Enable EasyOCR backend",
        env_fallback="OCR_ENABLE_EASYOCR",
        requires_reload=True,
    ),
    SettingDefinition(
        key="ocr.enable_paddleocr",
        category="ocr.providers",
        value_type="bool",
        default=False,
        description="Enable PaddleOCR backend",
        env_fallback="OCR_ENABLE_PADDLEOCR",
        requires_reload=True,
    ),
    SettingDefinition(
        key="ocr.enable_rapidocr",
        category="ocr.providers",
        value_type="bool",
        default=False,
        description="Enable RapidOCR backend (ONNX Runtime-based)",
        env_fallback="OCR_ENABLE_RAPIDOCR",
        requires_reload=True,
    ),
    SettingDefinition(
        key="ocr.enable_apple_vision",
        category="ocr.providers",
        value_type="bool",
        default=False,
        description="Enable Apple Vision backend (macOS only)",
        env_fallback="OCR_ENABLE_APPLE_VISION",
        requires_reload=True,
    ),
    SettingDefinition(
        key="ocr.enable_llm_proxy_vision",
        category="ocr.providers",
        value_type="bool",
        default=False,
        description="Enable LLM Proxy vision mode for OCR",
        env_fallback="OCR_ENABLE_LLM_PROXY_VISION",
        requires_reload=True,
    ),
    SettingDefinition(
        key="ocr.enable_llm_proxy_cloud",
        category="ocr.providers",
        value_type="bool",
        default=False,
        description="Enable LLM Proxy cloud mode for OCR",
        env_fallback="OCR_ENABLE_LLM_PROXY_CLOUD",
        requires_reload=True,
    ),

    # Processing configuration
    SettingDefinition(
        key="ocr.max_text_bytes",
        category="ocr.processing",
        value_type="int",
        default=51200,  # 50 KB
        description="Maximum output text size in bytes (truncates if exceeded)",
        env_fallback="OCR_MAX_TEXT_BYTES",
    ),
    SettingDefinition(
        key="ocr.min_valid_chars",
        category="ocr.processing",
        value_type="int",
        default=3,
        description="Minimum characters for valid OCR output",
        env_fallback="OCR_MIN_VALID_CHARS",
    ),
    SettingDefinition(
        key="ocr.language_default",
        category="ocr.processing",
        value_type="string",
        default="en",
        description="Default language hint for OCR",
        env_fallback="OCR_LANGUAGE_DEFAULT",
    ),
    SettingDefinition(
        key="ocr.max_attempts",
        category="ocr.processing",
        value_type="int",
        default=3,
        description="Maximum retry attempts for failed OCR jobs",
        env_fallback="OCR_MAX_ATTEMPTS",
    ),
    SettingDefinition(
        key="ocr.enabled_tiers",
        category="ocr.processing",
        value_type="string",
        default="tesseract,easyocr,paddleocr,rapidocr,apple_vision,llm_local,llm_cloud",
        description="Comma-separated list of enabled provider tiers for fallback",
        env_fallback="OCR_ENABLED_TIERS",
    ),
    SettingDefinition(
        key="ocr.validation_model",
        category="ocr.processing",
        value_type="string",
        default="lightweight",
        description="LLM model used for output validation",
        env_fallback="OCR_VALIDATION_MODEL",
    ),

    # Server configuration
    SettingDefinition(
        key="server.log_level",
        category="server",
        value_type="string",
        default="INFO",
        description="Logging level (DEBUG, INFO, WARNING, ERROR)",
        env_fallback="OCR_LOG_LEVEL",
    ),

    # Auth cache configuration
    SettingDefinition(
        key="auth.cache_ttl_seconds",
        category="auth",
        value_type="int",
        default=60,
        description="Auth validation cache TTL in seconds",
        env_fallback="JARVIS_APP_AUTH_CACHE_TTL_SECONDS",
    ),
]
