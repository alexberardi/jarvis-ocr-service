"""Tier mapping for OCR providers."""

# Map tier names to provider names
TIER_TO_PROVIDER = {
    "tesseract": "tesseract",
    "easyocr": "easyocr",
    "paddleocr": "paddleocr",
    "rapidocr": "rapidocr",
    "apple_vision": "apple_vision",
    "llm_local": "llm_proxy_vision",
    "llm_cloud": "llm_proxy_cloud"
}

# Reverse mapping
PROVIDER_TO_TIER = {v: k for k, v in TIER_TO_PROVIDER.items()}

# Default tier order (per PRD)
DEFAULT_TIER_ORDER = [
    "tesseract",
    "easyocr",
    "paddleocr",
    "rapidocr",
    "apple_vision",
    "llm_local",
    "llm_cloud"
]


def get_tier_order(enabled_tiers: list) -> list:
    """
    Get tier order, filtering to only enabled tiers.
    
    Args:
        enabled_tiers: List of enabled tier names
    
    Returns:
        Ordered list of enabled tiers
    """
    return [tier for tier in DEFAULT_TIER_ORDER if tier in enabled_tiers]


def provider_to_tier(provider_name: str) -> str:
    """
    Convert provider name to tier name.
    
    Args:
        provider_name: Provider name (e.g., "tesseract", "llm_proxy_vision")
    
    Returns:
        Tier name (e.g., "tesseract", "llm_local")
    """
    return PROVIDER_TO_TIER.get(provider_name, provider_name)


def tier_to_provider(tier_name: str) -> str:
    """
    Convert tier name to provider name.
    
    Args:
        tier_name: Tier name (e.g., "tesseract", "llm_local")
    
    Returns:
        Provider name (e.g., "tesseract", "llm_proxy_vision")
    """
    return TIER_TO_PROVIDER.get(tier_name, tier_name)

