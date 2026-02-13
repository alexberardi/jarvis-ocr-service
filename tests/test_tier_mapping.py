"""Tests for app/tier_mapping.py."""

from app.tier_mapping import (
    DEFAULT_TIER_ORDER,
    PROVIDER_TO_TIER,
    TIER_TO_PROVIDER,
    get_tier_order,
    provider_to_tier,
    tier_to_provider,
)


class TestTierToProvider:
    """Tests for tier_to_provider function."""

    def test_known_tier_tesseract(self):
        assert tier_to_provider("tesseract") == "tesseract"

    def test_known_tier_llm_local(self):
        assert tier_to_provider("llm_local") == "llm_proxy_vision"

    def test_known_tier_llm_cloud(self):
        assert tier_to_provider("llm_cloud") == "llm_proxy_cloud"

    def test_unknown_tier_returns_input(self):
        assert tier_to_provider("unknown_tier") == "unknown_tier"


class TestProviderToTier:
    """Tests for provider_to_tier function."""

    def test_known_provider_tesseract(self):
        assert provider_to_tier("tesseract") == "tesseract"

    def test_known_provider_llm_proxy_vision(self):
        assert provider_to_tier("llm_proxy_vision") == "llm_local"

    def test_known_provider_llm_proxy_cloud(self):
        assert provider_to_tier("llm_proxy_cloud") == "llm_cloud"

    def test_unknown_provider_returns_input(self):
        assert provider_to_tier("custom_provider") == "custom_provider"


class TestGetTierOrder:
    """Tests for get_tier_order function."""

    def test_all_enabled(self):
        result = get_tier_order(DEFAULT_TIER_ORDER)
        assert result == DEFAULT_TIER_ORDER

    def test_subset_preserves_order(self):
        result = get_tier_order(["llm_cloud", "tesseract"])
        assert result == ["tesseract", "llm_cloud"]

    def test_empty_enabled_returns_empty(self):
        result = get_tier_order([])
        assert result == []

    def test_unknown_tiers_filtered_out(self):
        result = get_tier_order(["unknown", "tesseract"])
        assert result == ["tesseract"]


class TestConstants:
    """Tests for module-level constants."""

    def test_tier_to_provider_has_all_default_tiers(self):
        for tier in DEFAULT_TIER_ORDER:
            assert tier in TIER_TO_PROVIDER

    def test_provider_to_tier_is_reverse_of_tier_to_provider(self):
        for tier, provider in TIER_TO_PROVIDER.items():
            assert PROVIDER_TO_TIER[provider] == tier

    def test_default_tier_order_length(self):
        assert len(DEFAULT_TIER_ORDER) == 7
