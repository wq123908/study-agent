from multiprocessing import context

from openai import OpenAI

from agent.config import Config
from agent.message import Message

class LLM:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.client = OpenAI(api_key=config.api_key, base_url=config.base_url)

    def request(self,messages: list[dict],tools:list | None = None):
        response = self.client.chat.completions.create(
            model=self.config.model,
            messages=messages,                    # 这次直接收 dict 列表
            temperature=0.7,
            tools=tools or None,                  # 空列表必须转成 None，否则接口报错
        )
        return response.choices[0].message  