"""Utility functions for Docker detection and environment checks."""

import os
import platform
import sys
from pathlib import Path


def is_running_in_docker() -> bool:
    """Detect if the service is running inside a Docker container."""
    # Check for Docker-specific files
    if Path("/.dockerenv").exists():
        return True
    
    # Check cgroup (Linux containers)
    try:
        with open("/proc/self/cgroup", "r") as f:
            content = f.read()
            if "docker" in content or "containerd" in content:
                return True
    except (FileNotFoundError, PermissionError):
        pass
    
    return False


def is_macos() -> bool:
    """Check if running on macOS."""
    return platform.system() == "Darwin"


def validate_apple_vision_environment() -> None:
    """Validate that Apple Vision can be used (macOS, not in Docker)."""
    if is_running_in_docker():
        raise RuntimeError(
            "Apple Vision cannot run inside Docker. "
            "Set OCR_ENABLE_APPLE_VISION=false or run natively on macOS."
        )
    
    if not is_macos():
        raise RuntimeError(
            "Apple Vision is only available on macOS. "
            f"Current platform: {platform.system()}"
        )

