import os
from langchain_openai import ChatOpenAI

# 单例模式
_llm_instance = None

def get_llm():
    global _llm_instance
    if _llm_instance is not None:
        return _llm_instance

    # 1. 安全获取并清洗环境变量
    raw_key = os.getenv("OPENAI_API_KEY", "").strip()
    clean_key = "".join(c for c in raw_key if ord(c) < 128)

    raw_model = os.getenv("MODEL_NAME", "Qwen/Qwen3-Coder-30B-A3B-Instruct").strip()
    clean_model = "".join(c for c in raw_model if ord(c) < 128)

    # 🚩 关键：获取中转地址
    api_base = os.getenv("OPENAI_API_BASE", "").strip()

    if not clean_key:
        print("❌ 错误：.env 中未找到有效的 OPENAI_API_KEY")
        return None

    try:
        # 2. 按照 curl 的参数对齐初始化
        # 2. 按照 OpenAI SDK 规范对齐初始化
        _llm_instance = ChatOpenAI(
            model=clean_model,
            api_key=clean_key,
            base_url=api_base if api_base else None,
            temperature=0.7,
            top_p=0.9,  # top_p 是标准参数，可以直接写在外面
            model_kwargs={
                # 🚩 核心修复：把非官方的自定义参数塞进 extra_body
                "extra_body": {
                    "repetition_penalty": 1.05,
                    "chat_template_kwargs": {
                        "enable_thinking": False
                    }
                }
            },
            timeout=60
        )
        print(f"✅ 大脑接入成功！地址: {api_base}")
        return _llm_instance
    except Exception as e:
        print(f"❌ 接入大模型失败: {e}")
        return None