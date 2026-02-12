#!/usr/bin/env python3
"""Entry point for Jarvis OCR Service."""

from pathlib import Path
from dotenv import load_dotenv
import uvicorn

# Load .env file from project root
env_path = Path(__file__).parent / ".env"
load_dotenv(env_path)

from app.config import config

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=config.OCR_PORT,
        log_level=config.OCR_LOG_LEVEL.lower()
    )

