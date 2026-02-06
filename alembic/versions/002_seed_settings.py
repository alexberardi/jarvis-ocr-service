"""Seed default settings

Revision ID: 002
Revises: 001
Create Date: 2026-02-05 17:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = '002'
down_revision = '001'
branch_labels = None
depends_on = None


# Settings definitions from app/services/settings_definitions.py
# All settings are safe to seed (no secrets or URLs)
SETTINGS = [
    # Provider enable/disable flags
    {
        "key": "ocr.enable_easyocr",
        "value": "false",
        "value_type": "bool",
        "category": "ocr.providers",
        "description": "Enable EasyOCR backend",
        "env_fallback": "OCR_ENABLE_EASYOCR",
        "requires_reload": True,
        "is_secret": False,
    },
    {
        "key": "ocr.enable_paddleocr",
        "value": "false",
        "value_type": "bool",
        "category": "ocr.providers",
        "description": "Enable PaddleOCR backend",
        "env_fallback": "OCR_ENABLE_PADDLEOCR",
        "requires_reload": True,
        "is_secret": False,
    },
    {
        "key": "ocr.enable_apple_vision",
        "value": "false",
        "value_type": "bool",
        "category": "ocr.providers",
        "description": "Enable Apple Vision backend (macOS only)",
        "env_fallback": "OCR_ENABLE_APPLE_VISION",
        "requires_reload": True,
        "is_secret": False,
    },
    {
        "key": "ocr.enable_llm_proxy_vision",
        "value": "false",
        "value_type": "bool",
        "category": "ocr.providers",
        "description": "Enable LLM Proxy vision mode for OCR",
        "env_fallback": "OCR_ENABLE_LLM_PROXY_VISION",
        "requires_reload": True,
        "is_secret": False,
    },
    {
        "key": "ocr.enable_llm_proxy_cloud",
        "value": "false",
        "value_type": "bool",
        "category": "ocr.providers",
        "description": "Enable LLM Proxy cloud mode for OCR",
        "env_fallback": "OCR_ENABLE_LLM_PROXY_CLOUD",
        "requires_reload": True,
        "is_secret": False,
    },
    # Processing configuration
    {
        "key": "ocr.max_text_bytes",
        "value": "51200",
        "value_type": "int",
        "category": "ocr.processing",
        "description": "Maximum output text size in bytes (truncates if exceeded)",
        "env_fallback": "OCR_MAX_TEXT_BYTES",
        "requires_reload": False,
        "is_secret": False,
    },
    {
        "key": "ocr.min_valid_chars",
        "value": "3",
        "value_type": "int",
        "category": "ocr.processing",
        "description": "Minimum characters for valid OCR output",
        "env_fallback": "OCR_MIN_VALID_CHARS",
        "requires_reload": False,
        "is_secret": False,
    },
    {
        "key": "ocr.language_default",
        "value": "en",
        "value_type": "string",
        "category": "ocr.processing",
        "description": "Default language hint for OCR",
        "env_fallback": "OCR_LANGUAGE_DEFAULT",
        "requires_reload": False,
        "is_secret": False,
    },
    {
        "key": "ocr.max_attempts",
        "value": "3",
        "value_type": "int",
        "category": "ocr.processing",
        "description": "Maximum retry attempts for failed OCR jobs",
        "env_fallback": "OCR_MAX_ATTEMPTS",
        "requires_reload": False,
        "is_secret": False,
    },
    {
        "key": "ocr.enabled_tiers",
        "value": "tesseract,easyocr,paddleocr,apple_vision,llm_local,llm_cloud",
        "value_type": "string",
        "category": "ocr.processing",
        "description": "Comma-separated list of enabled provider tiers for fallback",
        "env_fallback": "OCR_ENABLED_TIERS",
        "requires_reload": False,
        "is_secret": False,
    },
    {
        "key": "ocr.validation_model",
        "value": "lightweight",
        "value_type": "string",
        "category": "ocr.processing",
        "description": "LLM model used for output validation",
        "env_fallback": "OCR_VALIDATION_MODEL",
        "requires_reload": False,
        "is_secret": False,
    },
    # Server configuration
    {
        "key": "server.log_level",
        "value": "INFO",
        "value_type": "string",
        "category": "server",
        "description": "Logging level (DEBUG, INFO, WARNING, ERROR)",
        "env_fallback": "OCR_LOG_LEVEL",
        "requires_reload": False,
        "is_secret": False,
    },
    # Auth cache configuration
    {
        "key": "auth.cache_ttl_seconds",
        "value": "60",
        "value_type": "int",
        "category": "auth",
        "description": "Auth validation cache TTL in seconds",
        "env_fallback": "JARVIS_APP_AUTH_CACHE_TTL_SECONDS",
        "requires_reload": False,
        "is_secret": False,
    },
]


def upgrade() -> None:
    conn = op.get_bind()
    is_postgres = conn.dialect.name == 'postgresql'

    for setting in SETTINGS:
        if is_postgres:
            conn.execute(
                sa.text("""
                    INSERT INTO settings (key, value, value_type, category, description,
                                         env_fallback, requires_reload, is_secret,
                                         household_id, node_id, user_id)
                    VALUES (:key, :value, :value_type, :category, :description,
                           :env_fallback, :requires_reload, :is_secret,
                           NULL, NULL, NULL)
                    ON CONFLICT (key, household_id, node_id, user_id) DO NOTHING
                """),
                setting
            )
        else:
            conn.execute(
                sa.text("""
                    INSERT OR IGNORE INTO settings (key, value, value_type, category, description,
                                                   env_fallback, requires_reload, is_secret,
                                                   household_id, node_id, user_id)
                    VALUES (:key, :value, :value_type, :category, :description,
                           :env_fallback, :requires_reload, :is_secret,
                           NULL, NULL, NULL)
                """),
                setting
            )


def downgrade() -> None:
    conn = op.get_bind()
    for setting in SETTINGS:
        conn.execute(
            sa.text("""
                DELETE FROM settings
                WHERE key = :key
                  AND household_id IS NULL
                  AND node_id IS NULL
                  AND user_id IS NULL
            """),
            {"key": setting["key"]}
        )
