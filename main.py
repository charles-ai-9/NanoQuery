# -*- coding: utf-8 -*-
import os
import sys
import asyncio
import uuid
import warnings
import importlib
from pathlib import Path
from dotenv import load_dotenv

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


# ==========================================
# 🛠️ 辅助工具函数：案卷配置生成器
# ==========================================
def _new_config(thread_id: str, limit: int = 10) -> dict:
    return {
        "configurable": {
            "thread_id": thread_id,
            "user_name": "Jack探长",
            "role": "admin"  # 可以修改为admin or user，来测试不同权限下的行为差异
        },
        "recursion_limit": limit,
        "run_name": f"Financial_Detective_{thread_id}",
    }


# ==========================================
# 🚀 核心主程序 (异步执行)
# ==========================================

async def main() -> None:
    llm_instance = get_llm()
    if llm_instance is None:
        print("\n❌ 错误：无法初始化大模型。")
        return

    # 定义专属的记忆存储目录
    memory_dir = ROOT_DIR / "data" / "memory"
    memory_dir.mkdir(parents=True, exist_ok=True)
    db_path = str(memory_dir / "nanoquery.db")

    async with AsyncSqliteSaver.from_conn_string(db_path) as memory:

        print("╔══════════════════════════════════════════════════════╗")
        print("║      🕵️‍♂️ 金融风控侦探社 - V2.5 (人类接管版) 启动成功 ║")
        print("╚══════════════════════════════════════════════════════╝")

        custom_id = input("\n📂 请输入历史案卷号 (直接回车将开启新案卷): ").strip()
        thread_id = custom_id if custom_id else str(uuid.uuid4())[:8]

        print(f"▶️ 当前锁定案卷: {thread_id} | 记忆库: {db_path}")

        while True:
            try:
                question = input("\n💬 请下达指令（q 退出）：").strip()
            except (EOFError, KeyboardInterrupt):
                break

            if not question: continue
            if question.lower() in {"q", "exit", "quit"}: break

            try:
                import src.agent.nodes, src.agent.graph
                importlib.reload(src.agent.nodes)
                importlib.reload(src.agent.graph)
                ## 需要传入memory来构建图，以便支持持久化记忆和人类在环的状态篡改
                graph = src.agent.graph.build_graph(memory)

            except Exception as e:
                print(f"⚠️ 代码语法有误: {e}")
                continue

            try:
                print("\n" + "─" * 20 + " 🕵️‍♂️ 侦探社办案流水线 (Stream) " + "─" * 20)

                input_state = {"messages": [HumanMessage(content=question)]}

                limit_val = 20 if "分析" in question else 10
                config = _new_config(thread_id, limit=limit_val)

                # --- 1. 正常执行流式追踪 ---
                async for event in graph.astream(input_state, config, stream_mode="updates"):
                    for node_name, data in event.items():
                        print(f"📍 [节点通知]: {node_name.upper()} 处理完毕")

                        if "messages" in data:
                            new_msg = data["messages"][-1]
                            if isinstance(new_msg, AIMessage) and new_msg.content:
                                print(f"   📢 探员汇报: {new_msg.content}")
                            if isinstance(new_msg, AIMessage) and new_msg.tool_calls:
                                for tc in new_msg.tool_calls:
                                    print(f"   🔧 探员动作: 准备查数据库，调用 [{tc['name']}]")
                            if isinstance(new_msg, ToolMessage):
                                print(f"   📝 系统反馈: 数据库查询成功。")

                # =====================================================================
                # 🛑 2. 人类在环 (HITL)：审批与灵魂附体 (Update State)
                # =====================================================================
                # 获取当前图的最新状态快照
                current_state = await graph.aget_state(config)

                # 如果状态的 .next 列表里有 "tools"，说明程序是被 interrupt_before 挂起的
                if current_state.next and "tools" in current_state.next:
                    print("\n" + "⏸️ " * 15)
                    print("⚠️ [系统挂起]：探员正准备执行高危操作，等待探长审批！")

                    # 偷看探员脑子里想执行的 SQL
                    last_msg = current_state.values["messages"][-1]
                    if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
                        tool_call = last_msg.tool_calls[0]
                        original_sql = tool_call["args"].get("query", "")
                        print(f"🔍 拟执行 SQL: \033[93m{original_sql}\033[0m")

                    # 探长决策时间
                    action = input("⚖️ 审批意见 (y: 放行 / edit: 修改 SQL / n: 驳回): ").strip().lower()

                    if action == "y":
                        print("🟢 探长已放行，继续执行...")
                        # 传入 None 作为 input，表示从当前断点继续运行
                        async for event in graph.astream(None, config, stream_mode="updates"):
                            for node_name, data in event.items():
                                print(f"📍 [继续执行]: {node_name.upper()} 处理完毕")

                    ## 👻 灵魂附体 (Update State) 实战演示
                    elif action == "edit":
                        new_sql = input("📝 请输入正确的 SQL: ")

                        new_tool_call = {
                            "name": tool_call["name"],
                            "args": {"query": new_sql},
                            "id": tool_call["id"]
                        }

                        modified_msg = AIMessage(
                            # 🔑 关键操作 1：克隆 ID (id=last_msg.id)
                            # 在 LangGraph 的底层逻辑里，如果传入的新消息没有 ID 或者是一个新 ID，系统会把它追加 (Append) 到案卷的最后面。
                            # 但提取原来那句话的 last_msg.id，把带有相同 ID 的 modified_msg 塞进去时，就会触发“覆盖 (Overwrite)”机制。
                            # 探员原本想执行的那个错误 SQL，就在物理层面上被彻底抹除了。
                            id=last_msg.id,
                            content="探长暗中修改了我的记忆",
                            tool_calls=[new_tool_call]
                        )

                        # 🔑 关键操作 2：记忆注入 (aupdate_state)
                        # 这是 LangGraph 提供的官方“篡改后门”。通过 aupdate_state 告诉系统：“去档案柜（SQLite）里，找到当前 config 对应的案卷，把里面的消息强制更新掉。”
                        #
                        # 🔑 关键操作 3：完美伪装 (as_node="generate_sql")
                        # 如果只改了记忆，系统的“交通警察”会懵逼不知道下一步去哪。
                        # 加上 as_node="generate_sql" 就等于戴上了“大脑节点”的人皮面具。系统会以为是大脑自己生成的，然后顺理成章把正确的 SQL 交给 tools 去执行。
                        await graph.aupdate_state(config, {"messages": [modified_msg]}, as_node="generate_sql")

                        print("👻 灵魂附体完成！探员的记忆已被修改，正在用新 SQL 查库...")

                        # 重新启动图，从断点继续
                        async for event in graph.astream(None, config, stream_mode="updates"):
                            for node_name, data in event.items():
                                print(f"📍 [继续执行]: {node_name.upper()} 处理完毕")

                    else:
                        print("🛑 探长已驳回，当前任务终止。")
                # =====================================================================

                # --- 3. 结案陈词获取 ---
                final_state = await graph.aget_state(config)
                all_msgs = final_state.values.get("messages", [])
                final_ans = "探员似乎陷入了沉思..."

                # 倒序查找最后一条 AI 发出的、包含文本内容的消息
                for m in reversed(all_msgs):
                    if isinstance(m, AIMessage) and m.content and not m.tool_calls:
                        final_ans = m.content
                        break

                print("─" * 70)
                print(f"✅ 【最终调查报告】：\n{final_ans}")

            except GraphRecursionError:
                print("\n" + "!" * 20 + " 🚨 系统熔断报警 " + "!" * 20)
                print(f"❌ 办案失败：此任务在 {config['recursion_limit']} 步内未能结案。")
                print("💡 原因分析：可能由于 SQL 连续执行报错触发 AI 反复重试，或任务逻辑过于复杂。")
                print("🛠️ 建议：请尝试简化您的问题，或检查数据库表结构是否清晰。")
                print("!" * 55)

            except Exception as exc:
                print(f"\n❌ 办案异常：{type(exc).__name__} | {exc}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 侦探社已关闭，再见！")