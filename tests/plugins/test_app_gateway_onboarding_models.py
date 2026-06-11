"""App Gateway onboarding model catalog."""

from __future__ import annotations

from plugins.app_gateway.onboarding import (
    DEFAULT_ONBOARDING_MODELS,
    list_onboarding_models,
    resolve_onboarding_entry,
)


def test_default_onboarding_models_are_curated():
    models = list_onboarding_models()
    assert len(models) == 3
    assert [m["id"] for m in models] == [
        "deepseek-v4-flash",
        "kimi-k2.6",
        "poolside/laguna-m.1:free",
    ]


def test_config_onboarding_models_override_defaults():
    custom = [{"id": "only-one", "label": "One", "provider": "openrouter"}]
    assert list_onboarding_models(custom) == custom
    assert list_onboarding_models(custom) != DEFAULT_ONBOARDING_MODELS


def test_resolve_onboarding_entry_includes_base_url():
    resolved = resolve_onboarding_entry("kimi-k2.6")
    assert resolved["provider"] == "kimi-coding-cn"
    assert resolved["api_key_env"] == "KIMI_CN_API_KEY"
    assert resolved["base_url"] == "https://api.moonshot.cn/v1"
