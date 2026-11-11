from agent.core import Agent

agent = Agent(
    name="小助手",
    system_prompt="你是一个智能助手，你的任务是回答用户的问题。",
)

print("--- 第 1 轮 ---")
print("Agent:",agent.chat("你好,我叫DeepSeek"))

print("--- 第 2 轮 ---")
print("Agent:",agent.chat("我刚才说我叫什么？"))

print("--- 对话历史 ---")
agent.show_history()
