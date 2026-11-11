import json
from agent.message import ASSISTANT,SYSTEM,USER,Message
from agent.tools import TOOL_MAP

import logging
logger = logging.getLogger(__name__)


class Agent:
    def __init__(self, name: str, system_prompt: str, llm ,memory,tools=None) -> None:
        self.name = name
        self.system_prompt = system_prompt
        self.llm = llm
        self.memory = memory
        self.tools = tools or []
        self.messages:  list[Message] = self.memory.load()
        if not self.messages:
            self.messages.append(Message(role=SYSTEM, content=self.system_prompt))

    def chat(self,user_input: str) -> str:
        logger.info("用户输入: %s", user_input)     
        self.messages.append(Message(role=USER, content=user_input))
        reply = self._think()
        self.messages.append(Message(role=ASSISTANT, content=reply))
        self.memory.save(self.messages)
        logger.info("回复完成，历史共 %d 条", len(self.messages))
        return reply

    MAX_STEP = 5

    def _think(self) -> str:
        self.messages = self.memory.trim(self.messages, max_count=40)
        history = [message.to_dict() for message in self.messages]

        for step in range(1, self.MAX_STEP+1):
            message = self.llm.request(history,self.tools)
        
            if not message.tool_calls:
                return message.content or ""

            logger.info("第 %d 步，模型请求工具: %s", step, message.content)
            
            history.append({
                "role":ASSISTANT,
                "content":message.content,
                "tool_calls":[
                    {
                        "id":call.id,
                        "type":"function",
                        "function":{
                            "name":call.function.name,
                            "arguments":call.function.arguments,
                        }
                    }
                for call in message.tool_calls
                ],
            })

            for call in message.tool_calls:
                name = call.function.name
                arguments = json.loads(call.function.arguments or "{}")
                function = TOOL_MAP.get(name)
                output = function(**arguments) if function else f"工具 {name} 不存在"
                logger.info("调用工具 %s 参数 %s", name, arguments)
                history.append({
                    "role":"tool",
                    "tool_call_id":call.id,
                    "content":str(output),
                })
        
        return "(已到达最大调度步数，本次任务中止)"

    
    def show_history(self):
        for index, message in enumerate(self.messages, start=1):
            print(f"{index:>2}. {message.role:<9} | {message.content}")
              
