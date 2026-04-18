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

# ==========================================
# 🛑 日志消音配置 (保持终端整洁)
# ==========================================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 屏蔽底层库的无用日志
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("sentence_transformers").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("huggingface_hub").setLevel(logging.ERROR)

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
# 🛠️ 辅助工具函数
# ==========================================
def _new_config(thread_id: str, limit: int = 20) -> dict:
    return {
        "configurable": {
            "thread_id": thread_id,
            "user_name": "Jack",
            "role": "admin"
        },
        "recursion_limit": limit,
    }


# ==========================================
# 📺 核心 UI：全息事件流监听器 (打字机 + 进度直播)
# ==========================================
async def process_stream(graph_obj, state_input, run_config):
    """
    解析 LangGraph 事件流，实现 Token 级打印和工具状态播报
    """
    print("\n" + "─" * 20 + " ⚙️ Agent 实时流 (Stream) " + "─" * 20)

    try:
        # 使用 v2 版本的事件流协议
        async for event in graph_obj.astream_events(state_input, run_config, version="v2"):
            kind = event["event"]
            node_name = event.get("metadata", {}).get("langgraph_node", "")

            # 🎯 进度直播：监控工具启动，每个节点的进度的播报
            if kind == "on_tool_start":
                tool_name = event["name"]
                if tool_name == "execute_sql":
                    print(f"\n\033[96m[🔄 系统播报: 探员正在连接并查阅 SQLite 数据库...]\033[0m\n", end="", flush=True)
                elif tool_name == "search_knowledge_base":
                    print(f"\n\033[96m[📚 系统播报: 探员正在翻阅《星际金融风控手册...]\033[0m\n", end="", flush=True)
                else:
                    print(f"\n\033[96m[⚙️ 系统播报: 探员正在调用工具 {tool_name}...]\033[0m\n", end="", flush=True)

            # 🎯 打字机效果：捕捉大模型 Token，一个一个的吐给用户看。同时要注意streaming=True这个配置，不然事件流里是拿不到 chunk 的。
            elif kind == "on_chat_model_stream":
                # 过滤掉内部意图识别节点的输出，只显示最终回答节点的文字
                if node_name not in ["intent", "check_freshness"]:
                    chunk = event["data"]["chunk"]
                    if chunk.content:
                        print(chunk.content, end="", flush=True)

            # 内部神经元状态监控（可选）
            elif kind == "on_chain_end" and event["name"] == "intent":
                print(f"\n\033[90m[内部神经元: 意图已成功分发]\033[0m")

    except Exception as e:
        print(f"\n❌ 流式输出异常: {e}")

    print("\n" + "─" * 68)


# ==========================================
# 🚀 核心运行时 (Runtime)
# ==========================================
async def main() -> None:
    llm_instance = get_llm()
    if llm_instance is None:
        print("\n❌ 错误：无法初始化 LLM，请检查环境变量。")
        return

    memory_dir = ROOT_DIR / "data" / "memory"
    memory_dir.mkdir(parents=True, exist_ok=True)
    db_path = str(memory_dir / "nanoquery.db")

    # 挂载存储与记忆
    async with AsyncSqliteStore.from_conn_string(db_path) as global_store:
        await global_store.setup()
        async with AsyncSqliteSaver.from_conn_string(db_path) as memory:

            print("╔══════════════════════════════════════════════════════╗")
            print("║   🤖 金融风控 Agent 系统 - V4.5 (全能交互版)         ║")
            print("╚══════════════════════════════════════════════════════╝")

            while True:
                # ⚠️ 架构师提醒：遇到 InvalidParameter 报错时，换个全新的 ID 即可净化历史记忆
                custom_id = input("\n🔌 请输入 Session ID (直接回车生成，输入 exit 退出): ").strip()
                if custom_id.lower() == "exit": break

                thread_id = custom_id if custom_id else str(uuid.uuid4())[:8]
                print(f"▶️ [Runtime] 会话激活 | Thread ID: {thread_id}")

                while True:
                    try:
                        question = input(f"\n💬 [{thread_id}] 探长请提问 (q 终止会话)：").strip()
                    except (EOFError, KeyboardInterrupt):
                        break

                    if not question: continue
                    if question.lower() in {"q", "quit"}: break

                    try:
                        # 每次运行重新加载，方便调试修改后的代码
                        import src.agent.nodes, src.agent.graph
                        ## 动态加载模块，确保每次修改后都能生效（适合开发调试阶段，生产环境建议去掉）
                        importlib.reload(src.agent.nodes)
                        importlib.reload(src.agent.graph)

                        graph = src.agent.graph.build_graph_with_deps(memory, store=global_store)
                    except Exception as e:
                        print(f"⚠️ Graph 编译异常: {e}")
                        continue

                    try:
                        config = _new_config(thread_id)
                        input_state = {"messages": [HumanMessage(content=question)]}

                        # 1. 启动全息流输出
                        await process_stream(graph, input_state, config)

                        # 2. 检查是否有 HITL (人类在环) 挂起
                        current_state = await graph.aget_state(config)

                        # 循环处理可能的多次工具调用审批
                        while current_state.next and "tools" in current_state.next:
                            print("\n" + "⏸️ " * 15)
                            print("⚠️ [HITL 审批中]：探员请求操作，等待授权！")

                            last_msg = current_state.values["messages"][-1]
                            if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
                                for tc in last_msg.tool_calls:
                                    print(
                                        f"🔍 拟执行任务: \033[93m{tc['name']}\033[0m | 参数: \033[93m{tc['args']}\033[0m")

                            action = input("⚖️ 审批 (y: 放行 / edit: 修改参数 / n: 驳回): ").strip().lower()

                            if action == "y":
                                print("🟢 审批通过，继续执行...")
                                await process_stream(graph, None, config)
                            elif action == "edit":
                                # 简化版 edit：这里假设修改第一个参数
                                field = list(tc['args'].keys())[0]
                                new_val = input(f"📝 请输入新的 {field}: ")
                                new_tool_call = {
                                    "name": tc["name"],
                                    "args": {field: new_val},
                                    "id": tc["id"]
                                }
                                modified_msg = AIMessage(
                                    id=last_msg.id,
                                    content="状态已被人类覆写",
                                    tool_calls=[new_tool_call]
                                )
                                await graph.aupdate_state(config, {"messages": [modified_msg]}, as_node="generate_sql")
                                print("👻 状态已覆写，继续执行...")
                                await process_stream(graph, None, config)
                            else:
                                print("🛑 审批驳回。")
                                break

                            current_state = await graph.aget_state(config)

                        # 3. 🛡️ 最终答案兜底打印 (防止流式输出漏掉)
                        final_state = await graph.aget_state(config)
                        all_msgs = final_state.values.get("messages", [])
                        final_ans = ""
                        for m in reversed(all_msgs):
                            if isinstance(m, AIMessage) and m.content and not m.tool_calls:
                                final_ans = m.content
                                break

                        if final_ans:
                            print(f"\n\033[92m✅ 【最终报告】：\n{final_ans}\033[0m")

                    except GraphRecursionError:
                        print("\n🚨 触发递归限制，执行中断。")
                    except Exception as exc:
                        print(f"\n❌ 运行时异常：{exc}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 探员下班了，探长慢走！")