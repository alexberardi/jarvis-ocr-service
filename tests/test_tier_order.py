"""Guards on the `auto` provider chain.

The order lived in two places — tier_mapping.DEFAULT_TIER_ORDER and a literal
list inside provider_manager — under different names for the LLM tiers. They had
already drifted, and only the provider_manager copy governed `auto`, which is the
mode jarvis-recipes-server uses. Reordering the other one changed nothing that
runs. Nothing failed when they disagreed, so these pin the contract.
"""
import inspect

from app.tier_mapping import DEFAULT_TIER_ORDER, TIER_TO_PROVIDER, tier_to_provider


def test_auto_order_is_derived_not_duplicated():
    """provider_manager must not carry its own copy of the chain."""
    from app import provider_manager

    src = inspect.getsource(provider_manager)
    assert "DEFAULT_TIER_ORDER" in src, (
        "the auto chain must come from tier_mapping.DEFAULT_TIER_ORDER"
    )
    # The old literal, in either naming scheme.
    assert '"tesseract", "easyocr", "paddleocr", "rapidocr"' not in src, (
        "a second hardcoded provider order has reappeared in provider_manager"
    )


def test_every_tier_maps_to_a_known_provider():
    for tier in DEFAULT_TIER_ORDER:
        assert tier in TIER_TO_PROVIDER, f"{tier} has no provider mapping"


def test_cheap_accurate_providers_come_before_expensive_weak_ones():
    """Ordered by measured recall-per-second; see benchmarks/ocr-providers/.

    easyocr measured 43.5% recall at 18s/img and 14GB peak RSS, and sat second in
    the original order. paddleocr never finished the corpus. Neither should be
    reached by `auto` before rapidocr or tesseract.
    """
    pos = {t: i for i, t in enumerate(DEFAULT_TIER_ORDER)}

    for weak in ("easyocr", "paddleocr"):
        for good in ("rapidocr", "tesseract"):
            assert pos[weak] > pos[good], f"{weak} must not precede {good}"


def test_local_providers_come_before_the_llm_tiers():
    """The LLM tiers cost a model call; they are a fallback, not a first resort."""
    pos = {t: i for i, t in enumerate(DEFAULT_TIER_ORDER)}

    for local in ("rapidocr", "tesseract"):
        for llm in ("llm_local", "llm_cloud"):
            assert pos[local] < pos[llm], f"{local} must precede {llm}"


def test_llm_cloud_is_the_last_resort_among_llm_tiers():
    pos = {t: i for i, t in enumerate(DEFAULT_TIER_ORDER)}
    assert pos["llm_local"] < pos["llm_cloud"]


def test_derived_order_uses_provider_names_not_tier_names():
    """The two vocabularies are the thing that drifted: the chain is consumed as
    provider names ("llm_proxy_vision"), while the source list is tier names
    ("llm_local")."""
    derived = [tier_to_provider(t) for t in DEFAULT_TIER_ORDER]

    assert "llm_proxy_vision" in derived
    assert "llm_local" not in derived
