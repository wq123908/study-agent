import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()

@dataclass
class Config:
    api_key:str
    base_url:str
    model:str 

def load_config() -> Config:
    api_key = os.getenv("DEEPSEEK_API_KEY").strip()
    if  not api_key or api_key.startswith("sk-your-key"):
        raise RuntimeError("请在项目根目录 .env 中填写真实的 DEEPSEEK_API_KEY")
    return Config(
        api_key=api_key,
        base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),  # 第二个参数是默认值
        model=os.getenv("DEEPSEEK_MODEL", "deepseek-flash"),
    )

