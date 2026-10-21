"""The only production model transport. SDK retries are disabled."""

import os
from typing import Protocol

from langchain_core.messages import AIMessage
from langchain_openai import ChatOpenAI


class ModelAdapter(Protocol):
    async def invoke(self, role, agent_id, messages, tools, config) -> AIMessage: ...


class OpenAIChatCompletionsAdapter:
    def __init__(self):
        self.api_key = os.environ["OPENAI_API_KEY"]
        self.base_url = os.environ["OPENAI_BASE_URL"]
        if not self.api_key.strip() or not self.base_url.strip():
            raise ValueError("OPENAI_API_KEY and OPENAI_BASE_URL must be nonempty")
        self.models = {}

    async def invoke(self, role, agent_id, messages, tools, config):
        if role not in self.models:
            self.models[role] = ChatOpenAI(
                model=config.model,
                api_key=self.api_key,
                base_url=self.base_url,
                use_responses_api=False,
                max_tokens=config.max_output_tokens,
                max_retries=0,
                **config.options,
            )
        model = self.models[role]
        if tools:
            model = model.bind_tools(tools)
        return await model.ainvoke(messages)
