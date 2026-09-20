from kernel.ai_gateway.providers.anthropic import AnthropicProvider
from kernel.ai_gateway.providers.base import Completion, Provider, Request
from kernel.ai_gateway.providers.google import GoogleProvider
from kernel.ai_gateway.providers.openai_compat import LocalProvider, OpenAICompatibleProvider

_ALL: tuple[Provider, ...] = (
    AnthropicProvider(),
    OpenAICompatibleProvider(),
    GoogleProvider(),
    LocalProvider(),
)

REGISTRY: dict[str, Provider] = {provider.name: provider for provider in _ALL}

__all__ = [
    "REGISTRY",
    "AnthropicProvider",
    "Completion",
    "GoogleProvider",
    "LocalProvider",
    "OpenAICompatibleProvider",
    "Provider",
    "Request",
]
