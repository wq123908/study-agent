from __future__ import annotations

from openai import OpenAI

from agent.config import Config 

class LLM:
    def __init__(self,config:Config) -> None:
        self.config = config
        self.client = OpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
            timeout=config.request_timeout,
        ) 

    def request(self, messages: list[dict], tools: list | None = None):
        response = self.client.chat.completions.create(
            model=self.config.model,
            messages=messages,
            temperature=self.config.temperature,
            tools=tools or None
        )
        return response.choices[0].message