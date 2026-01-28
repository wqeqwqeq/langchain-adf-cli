"""Azure AI Foundry Claude integration for LangChain."""

from functools import cached_property

from langchain_anthropic import ChatAnthropic
from anthropic import AnthropicFoundry, AsyncAnthropicFoundry


class ChatAzureFoundryClaude(ChatAnthropic):
    """ChatAnthropic for Azure AI Foundry (API Key auth)."""

    @cached_property
    def _client(self) -> AnthropicFoundry:
        return AnthropicFoundry(
            api_key=self.anthropic_api_key.get_secret_value(),
            base_url=self.anthropic_api_url,
            max_retries=self.max_retries,
            timeout=self.default_request_timeout,
        )

    @cached_property
    def _async_client(self) -> AsyncAnthropicFoundry:
        return AsyncAnthropicFoundry(
            api_key=self.anthropic_api_key.get_secret_value(),
            base_url=self.anthropic_api_url,
            max_retries=self.max_retries,
            timeout=self.default_request_timeout,
        )
