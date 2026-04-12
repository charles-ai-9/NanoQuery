# -*- coding: utf-8 -*-
import os
import sys
import asyncio
import uuid
import warnings
import importlib
from pathlib import Path
from dotenv import load_dotenv
import logging

# 这是你原有的全局设置
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 👇 新增这行“消音代码”：强制让 httpx 只有在发生警告或错误时才说话
logging.getLogger("httpx").setLevel(logging.WARNING)

# 如果你嫌 transformers 相关的加载日志也烦，也可以顺手静音：
logging.getLogger("sentence_transformers").setLevel(logging.WARNING)


# --- 1. 环境初始化 ---
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

os.environ["PYTHONIOENCODING"] = "utf-8"
os.environ["PYTHONUTF8"] = "1"

ROOT_DIR = Path(__file__).parent.absolute()
sys.path.insert(0, str(ROOT_DIR))

load_dotenv(dotenv_path=ROOT_DIR / ".env")
warnings.filterwarnings("ignore")

from langgraph.errors import GraphRecursionError
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from src.core.llm_client import get_llm

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.store.sqlite.aio import AsyncSqliteStore


# ==========================================
# 🛠️ 辅助工具函数：Graph Config 生成器
# ==========================================
def _new_config(thread_id: str, limit: int = 10) -> dict:
    return {
        "configurable": {
            "thread_id": thread_id,  # 核心：Session 的唯一标识
            "user_name": "Jack",
            "role": "admin"
        },
        "recursion_limit": limit,
        "run_name": f"Financial_Agent_{thread_id}",
    }


# ==========================================
# 🚀 核心运行时 (Runtime)
# ==========================================

async def main() -> None:
    llm_instance = get_llm()
    if llm_instance is None:
        print("\n❌ 错误：无法初始化 LLM，请检查环境变量。")
        return

    # 定义 Checkpointer 和 Store 的存储路径
    memory_dir = ROOT_DIR / "data" / "memory"
    memory_dir.mkdir(parents=True, exist_ok=True)
    db_path = str(memory_dir / "nanoquery.db")

    # =====================================================================
    # 🏢 挂载 Store API (长期语义记忆) & Checkpointer (短期状态快照)
    # =====================================================================
    async with AsyncSqliteStore.from_conn_string(db_path) as global_store:
        # 初始化 Store 底层表结构
        await global_store.setup()

        async with AsyncSqliteSaver.from_conn_string(db_path) as memory:

            print("╔══════════════════════════════════════════════════════╗")
            print("║     🤖 金融风控 Agent 系统 - V3.0 (Store API 挂载版) ║")
            print("╚══════════════════════════════════════════════════════╝")

            # 🔄 外层循环：管理 Thread (会话) 级生命周期
            while True:
                custom_id = input("\n🔌 请输入 Session ID (直接回车生成新 Thread，输入 exit 彻底退出): ").strip()
                if custom_id.lower() == "exit":
                    break

                thread_id = custom_id if custom_id else str(uuid.uuid4())[:8]
                print(f"▶️ [Runtime] 当前 Thread ID: {thread_id} | Checkpointer DB: {db_path}")

                # 🔄 内层循环：处理当前 Thread 内的流式交互
                while True:
                    try:
                        question = input(f"\n💬 [{thread_id}] 请输入 Prompt (输入 q 终止当前 Session)：").strip()
                    except (EOFError, KeyboardInterrupt):
                        break

                    if not question: continue

                    if question.lower() in {"q", "quit"}:
                        print("🔒 当前 Session 已终止。")
                        break

                    try:
                        import src.agent.nodes, src.agent.graph
                        importlib.reload(src.agent.nodes)
                        importlib.reload(src.agent.graph)

                        # 本地运行：调用 build_graph_with_deps，手动注入 checkpointer 和 store
                        graph = src.agent.graph.build_graph_with_deps(memory, store=global_store)

                    except Exception as e:
                        print(f"⚠️ Graph 编译异常: {e}")
                        continue

                    try:
                        print("\n" + "─" * 20 + " ⚙️ Agent Graph 执行流 (Stream) " + "─" * 20)

                        input_state = {"messages": [HumanMessage(content=question)]}

                        limit_val = 20 if "分析" in question else 10
                        config = _new_config(thread_id, limit=limit_val)

                        # --- 1. Graph 流式输出 (Stream Updates) ---
                        async for event in graph.astream(input_state, config, stream_mode="updates"):
                            for node_name, data in event.items():
                                print(f"📍 [Node Event]: {node_name.upper()} 执行完毕")

                                if "messages" in data:
                                    new_msg = data["messages"][-1]
                                    if isinstance(new_msg, AIMessage) and new_msg.content:
                                        print(f"   🤖 Agent 回复: {new_msg.content}")
                                    if isinstance(new_msg, AIMessage) and new_msg.tool_calls:
                                        for tc in new_msg.tool_calls:
                                            print(f"   🔧 Tool Call: 准备调用工具 [{tc['name']}]")
                                    if isinstance(new_msg, ToolMessage):
                                        print(f"   📝 Tool Result: 工具执行成功。")

                        # =====================================================================
                        # 🛑 2. 人类在环 (HITL) 与 状态篡改 (Update State)
                        # =====================================================================
                        current_state = await graph.aget_state(config)

                        if current_state.next and "tools" in current_state.next:
                            print("\n" + "⏸️ " * 15)
                            print("⚠️ [HITL 挂起]：流程已在 tools 节点前中断，等待人类审批！")

                            last_msg = current_state.values["messages"][-1]
                            if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
                                tool_call = last_msg.tool_calls[0]
                                original_sql = tool_call["args"].get("query", "")
                                print(f"🔍 拟执行 SQL: \033[93m{original_sql}\033[0m")

                            action = input("⚖️ HITL 审批 (y: 放行 / edit: 修改 SQL / n: 驳回): ").strip().lower()

                            if action == "y":
                                print("🟢 审批通过 (Proceed)，继续执行 Graph...")
                                async for event in graph.astream(None, config, stream_mode="updates"):
                                    for node_name, data in event.items():
                                        print(f"📍 [Node Event]: {node_name.upper()} 执行完毕")

                            elif action == "edit":
                                new_sql = input("📝 请输入修正后的 SQL: ")

                                new_tool_call = {
                                    "name": tool_call["name"],
                                    "args": {"query": new_sql},
                                    "id": tool_call["id"]
                                }

                                modified_msg = AIMessage(
                                    id=last_msg.id,  # 覆盖原有 State 的核心
                                    content="状态已被人类通过 Update State 覆写",
                                    tool_calls=[new_tool_call]
                                )

                                # 强行更新图的内部状态，伪装成 generate_sql 节点
                                await graph.aupdate_state(config, {"messages": [modified_msg]}, as_node="generate_sql")
                                print("👻 Update State 完成！已覆写当前 Thread 状态，使用新 SQL 继续流转...")

                                async for event in graph.astream(None, config, stream_mode="updates"):
                                    for node_name, data in event.items():
                                        print(f"📍 [Node Event]: {node_name.upper()} 执行完毕")

                            else:
                                print("🛑 审批驳回，当前 Session 流转中断。")
                        # =====================================================================

                        # --- 3. 获取最终 State ---
                        final_state = await graph.aget_state(config)
                        all_msgs = final_state.values.get("messages", [])
                        final_ans = "Agent 未返回有效文本内容..."

                        for m in reversed(all_msgs):
                            if isinstance(m, AIMessage) and m.content and not m.tool_calls:
                                final_ans = m.content
                                break

                        print("─" * 70)
                        print(f"✅ 【Final Response / 最终输出】：\n{final_ans}")

                    except GraphRecursionError:
                        print("\n" + "!" * 20 + " 🚨 触发 Recursion Limit " + "!" * 20)
                        print(f"❌ 执行失败：Graph 在 {config['recursion_limit']} 步内未能触达 END 节点。")
                        print("💡 原因分析：可能由于 Tool 连续报错触发 ReAct 循环重试，或业务流转陷入死循环。")
                        print("!" * 55)

                    except Exception as exc:
                        print(f"\n❌ 运行时异常：{type(exc).__name__} | {exc}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Agent Runtime 已安全退出，再见！")