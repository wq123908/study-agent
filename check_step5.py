from agent.config import load_config
from agent.core import Agent
from agent.llm import LLM
from agent.memory import Memory
from agent.tools import TOOLS

agent = Agent(
    name="小助手",
    system_prompt="你是一个简洁的助手。涉及时间、日期或计算时，必须调用工具获取准确结果，不要猜测。",
    llm=LLM(load_config()),
    memory=Memory("memory5.json"),        # 换个文件，不和阶段 4 的历史混在一起
    tools=TOOLS,
)

print("--- 问时间 ---")
print("Agent:", agent.chat("现在几点了？"))

print("--- 问计算 ---")
print("Agent:", agent.chat("帮我算一下 1234 * 5678 等于多少"))