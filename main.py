# -*- coding: utf-8 -*-
import os
import sys
import io
import asyncio
import uuid
import warnings
import importlib
from pathlib import Path
# ==========================================
# 🔥 第一步：环境编码硬修复 (全局唯一一次，放在最前面)
# ==========================================
# 1. 尝试让系统 locale 支持 UTF-8
import locale

try:
    locale.setlocale(locale.LC_ALL, 'en_US.UTF-8')
except:
    pass

# 2. 只有在确实不是 UTF-8 的情况下才包装流，避免 I/O operation on closed file
if sys.stdout.encoding is None or sys.stdout.encoding.upper() != 'UTF-8':
    try:
        # 强制指定 line_buffering=True 确保输出即时
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', line_buffering=True)
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', line_buffering=True)
        sys.stdin = io.TextIOWrapper(sys.stdin.buffer, encoding='utf-8')
    except (AttributeError, Exception):
        pass

# 3. 设置全局环境变量
os.environ["PYTHONIOENCODING"] = "utf-8"

print(f"[系统自检] 侦探社编码检查: {sys.stdout.encoding or '未知'}")

# ==========================================
# 🔥 第二步：路径与环境加载
# ==========================================
from dotenv import load_dotenv

# 动态获取当前脚本所在的绝对路径
ROOT_DIR = Path(__file__).parent.absolute()
sys.path.insert(0, str(ROOT_DIR))

# 显式加载 .env 文件
load_dotenv(dotenv_path=ROOT_DIR / ".env")
warnings.filterwarnings("ignore")

from langchain_core.messages import HumanMessage
from src.core.llm_client import get_llm
from src.agent.nodes import initialize_llm


def _new_config(thread_id: str) -> dict:
    return {
        "configurable": {"thread_id": thread_id},
        "run_name": f"Financial_Detective_{thread_id}",
    }

async def main() -> None:
    # 1. 初始化大模型
    llm_instance = get_llm()
    if llm_instance is None:
        print("\n❌ 无法连接到大模型！请检查 .env 配置。")
        return

    initialize_llm(llm_instance)
    thread_id = str(uuid.uuid4())[:8]

    print("╔══════════════════════════════════════════════════════╗")
    print("║      🕵️‍♂️ 金融风控侦探社 - 最终修复版启动成功           ║")
    print(f"║      环境: {sys.platform} | 会话ID: {thread_id}            ║")
    print("╚══════════════════════════════════════════════════════╝")

    while True:
        try:
            question = input("\n💬 请提问（输入 q 退出）：").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if not question: continue
        if question.lower() in {"q", "exit", "quit"}: break

        # --- 2. 热加载逻辑 ---
        try:
            import src.agent.nodes, src.agent.graph
            importlib.reload(src.agent.nodes)
            importlib.reload(src.agent.graph)
            from src.agent.nodes import initialize_llm as re_init
            re_init(llm_instance)
            graph = src.agent.graph.build_graph()
        except Exception as e:
            print(f"⚠️ 热加载失败: {e}")
            continue

        try:
            # 3. 执行任务
            initial_state = {
                "messages": [HumanMessage(content=question)],
                "route": "", "data_freshness": "", "sql_result": "", "analysis": ""
            }

            # 重要：确保结果处理在 UTF-8 环境下
            result = await graph.ainvoke(initial_state, config=_new_config(thread_id))

            # 4. 展示逻辑
            current_route = result.get("route", "business")
            final_ans = result["messages"][-1].content if result.get("messages") else "无返回内容"

            if current_route == "chat":
                print(f"\n💬 侦探回复：{final_ans}")
            elif current_route == "meta":
                print(f"\n🔍 结构探查结果：\n{final_ans}")
            elif current_route == "analysis":
                report = result.get("analysis") or final_ans
                print(f"\n🕵️‍♂️ 重案组分析报告：\n{report}")
            else:
                print(f"\n🔍 侦探调查结论：\n{final_ans}")

        except Exception as exc:
            print(f"\n❌ 办案过程中出现异常：{type(exc).__name__}")
            # 此时如果还报错，尝试用简单编码打印错误
            try:
                print(f"详情: {exc}")
            except:
                print("详情包含无法显示的字符。")


if __name__ == "__main__":
    asyncio.run(main())