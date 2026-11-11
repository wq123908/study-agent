from agent.core import Agent
from agent.llm import LLM
from agent.config import load_config

config = load_config()
print("模型   :", config.model)
print("服务地址:", config.base_url)

agent = Agent(
    name="小助",
    system_prompt="你是一个智能助手，能够回答用户的问题。",
    llm=LLM(config),
)

print("--- 真实模型回复 ---")
print("用户：用一句话介绍你自己")
print("Agent：", agent.chat("用一句话介绍你自己"))

print("--- 消息列表 ---")
agent.show_history()
