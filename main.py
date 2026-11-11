from agent.config import load_config
from agent.core import Agent
from agent.llm import LLM
from agent.memory import Memory
from agent.tools import TOOLS

import logging

logging.basicConfig(
    level=logging.INFO,                                  # 低于 INFO 的不显示
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
logging.getLogger("httpx2").setLevel(logging.WARNING)   # 屏蔽 SDK 的请求日志
logging.getLogger("httpx").setLevel(logging.WARNING)    # 兼容旧版命名


agent = Agent(
    name="小助手",
    system_prompt=(
        "你是小助手，一个由 DeepSeek 模型驱动的中文 AI 助手。"
        "如果有人问你的身份或底层模型，如实说明你是基于 DeepSeek 的助手，"
        "不要声称自己是其他公司的模型。"
        "你是一个简洁的助手，回答不超过三句话。"
        "涉及时间、日期或计算时，必须调用工具获取准确结果，不要猜测。"
    ),
    llm=LLM(load_config()),
    memory=Memory("memory.json"),
    tools=TOOLS,
)

print("开始对话，输入 exit 结束")
while True:
    try:
        text = input("你：")
    except KeyboardInterrupt:              # 用户按 Ctrl+C
        print("\n再见！")
        break

    if text.strip().lower() == "exit":
        print("再见！")
        break

    if not text.strip():                   # 直接回车，忽略
        continue

    try:
        print("Agent：", agent.chat(text))
    except Exception as error:             # 任何意外都不能终止对话
        print(f"  [错误] {type(error).__name__}: {error}")
        print("  （这一轮失败了，可以重新提问）")