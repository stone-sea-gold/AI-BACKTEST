"""v2 测试：Provider 创建与配置。"""

from aiquant.providers.base import LLMConfig, is_anthropic, PROVIDER_URL_MAP


def test_url_mapping():
    assert PROVIDER_URL_MAP["deepseek"] == "https://api.deepseek.com/v1"
    assert PROVIDER_URL_MAP["claude"] == "https://api.anthropic.com"
    assert PROVIDER_URL_MAP["openai"] == "https://api.openai.com/v1"


def test_is_anthropic_claude_provider():
    config = LLMConfig(provider="claude", api_key="sk-ant-xxx")
    assert is_anthropic(config) is True


def test_is_anthropic_ant_key():
    config = LLMConfig(provider="deepseek", api_key="sk-ant-xxx")
    assert is_anthropic(config) is True


def test_is_not_anthropic():
    config = LLMConfig(provider="deepseek", api_key="sk-xxx")
    assert is_anthropic(config) is False


def test_create_deepseek_provider():
    from aiquant.providers.deepseek_provider import DeepSeekProvider
    config = LLMConfig(provider="deepseek", api_key="test-key")
    provider = DeepSeekProvider(config)
    assert provider.base_url == "https://api.deepseek.com/v1"


def test_create_openai_provider():
    from aiquant.providers.openai_provider import OpenAIProvider
    config = LLMConfig(provider="openai", api_key="test-key")
    provider = OpenAIProvider(config)
    assert provider.base_url == "https://api.openai.com/v1"


def test_other_provider_requires_base_url():
    from aiquant.providers.openai_provider import OpenAIProvider
    config = LLMConfig(provider="other", api_key="test-key")
    try:
        OpenAIProvider(config)
        assert False, "应该抛出 ValueError"
    except ValueError:
        pass


def test_other_provider_with_base_url():
    from aiquant.providers.openai_provider import OpenAIProvider
    config = LLMConfig(provider="other", api_key="test-key", base_url="http://localhost:8000")
    provider = OpenAIProvider(config)
    assert provider.base_url == "http://localhost:8000"
