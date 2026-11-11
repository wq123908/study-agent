from datetime import datetime

def get_current_time() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def calculator(expression: str) -> str:
    try:
        return eval(expression,{"__builtins__":None})
    except Exception as error:
        return f"计算错误：{error}"
    return str(result)
    
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_current_time",
            "description": "获取当前的日期和时间，用户问时间、日期、今天几号时使用",
            "parameters": {"type": "object", "properties": {}},
        }
    },
    {
        "type": "function",
        "function": {
            "name": "calculator",
            "description": "计算数学表达式，支持加减乘除和括号，例如 12*(3+4)",
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "要计算的数学表达式",
                    }
                },
                "required": ["expression"],                # 哪些参数必填
            },
        },
    }
]

TOOL_MAP = {
    "get_current_time": get_current_time,
    "calculator": calculator,
}