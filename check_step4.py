import sys

from agent.config import load_config
from agent.memory import Memory
from agent.core import Agent
from agent.llm import LLM

text = sys.argv[1] if len(sys.argv) > 1 else "你好"

agent = Agent(
    name="小助手",
    system_prompt="你是一个专业的助手",
    llm=LLM(load_config()),
    memory=Memory("memory.json"),
)

print("你：",text)
print("小助手：",agent.chat(text))
print("---- 历史记录 ----")
agent.show_history()
