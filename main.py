# -*- coding: utf-8 -*-
import os
import sys

# 必须在所有其他导入之前强制将 stdout/stderr 重新绑定为 UTF-8
# 这样可以确保 print 中文/emoji 不会因终端编码为 ASCII 而报 UnicodeEncodeError
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

os.environ["PYTHONIOENCODING"] = "utf-8"
os.environ["PYTHONUTF8"] = "1"

import asyncio
import uuid
import warnings
import importlib
from pathlib import Path
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).parent.absolute()
sys.path.insert(0, str(ROOT_DIR))

# 加载环境变量
load_dotenv(dotenv_path=ROOT_DIR / ".env")
warnings.filterwarnings("ignore")

# 延迟导入业务模块，确保环境变量先加载
from langchain_core.messages import HumanMessage
from src.core.llm_client import get_llm


print(f"[系统自检] 环境就绪 | 编码: {sys.stdout.encoding} | 路径: {ROOT_DIR.name}")

# ==========================================
# 🔥 第二步：核心逻辑
# ==========================================

def _new_config(thread_id: str) -> dict:
    return {
        "configurable": {"thread_id": thread_id},
        "run_name": f"Financial_Detective_{thread_id}",
    }

async def main() -> None:
    # 1. 初始化大模型 (单例模式)
    llm_instance = get_llm()
    if llm_instance is None:
        print("\n❌ 无法连接到大模型！请检查 .env 配置或网络。")
        return


    thread_id = str(uuid.uuid4())[:8]

    print("╔══════════════════════════════════════════════════════╗")
    print("║      🕵️‍♂️ 金融风控侦探社 - 生产就绪版启动成功           ║")
    print(f"║      会话ID: {thread_id} | 状态: 运行中                     ║")
    print("╚══════════════════════════════════════════════════════╝")

    while True:
        try:
            question = input("\n💬 请提问（输入 q 退出）：").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if not question: continue
        if question.lower() in {"q", "exit", "quit"}: break

        # --- 2. 热加载逻辑 (支持动态修改代码后即时生效) ---
        try:
            import src.agent.nodes, src.agent.graph
            importlib.reload(src.agent.nodes)
            importlib.reload(src.agent.graph)
            graph = src.agent.graph.build_graph()
        except Exception as e:
            print(f"⚠️ 模块热加载失败，请检查语法: {e}")
            continue

        try:
            # 3. 构建初始状态
            initial_state = {
                "messages": [HumanMessage(content=question)],
                "route": "",
                "data_freshness": "",
                "sql_result": "",
                "analysis": ""
            }

            # 4. 执行 LangGraph 工作流
            result = await graph.ainvoke(initial_state, config=_new_config(thread_id))

            # 5. 分流展示输出
            current_route = result.get("route", "business")
            final_ans = result["messages"][-1].content if result.get("messages") else "无返回内容"

            if current_route == "chat":
                print(f"\n💬 侦探回复：{final_ans}")
            elif current_route == "meta":
                print(f"\n🔍 结构探查结果：\n{final_ans}")
            elif current_route == "analysis":
                report = result.get("analysis") or final_ans
                print(f"\n🕵️‍♂️ 重案组深度分析报告：\n{report}")
            else:
                # 普通业务查询展示数据水位
                if result.get("data_freshness"):
                    print(f"📅 哨兵：数据最新日期为 [{result['data_freshness']}]")
                print(f"\n🔍 侦探调查结论：\n{final_ans}")

        except Exception as exc:
            print(f"\n❌ 办案过程中出现异常：{type(exc).__name__}")
            print(f"   详情: {exc}")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 侦探社已关闭。")