"""
graph.py - NanoQuery 拓扑升级：支持工具执行循环
"""
import sys
import os

# langgraph dev 加载此模块时 stdout 可能为 ASCII 编码
# 在此处强制重绑定为 UTF-8，防止任何中文/emoji 输出触发 UnicodeEncodeError
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
os.environ["PYTHONIOENCODING"] = "utf-8"

from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition
## 在标准的单次对话中（没有停顿），程序一气呵成跑完，用内存里的临时变量就足够了。
# 但是，一旦引入了 HITL（人类干预） 也就是 interrupt_before，程序的运行会被强行挂起（暂停）。
from langgraph.checkpoint.memory import MemorySaver
from src.agent.nodes import check_data_freshness_node, generate_sql_node, intent_node
from src.agent.state import MessagesState
from src.tools.sql_tools import execute_sql
from src.agent.subgraphs.rca_graph import rca_graph

# 意图路由器，根据当前会话状态决定流程走向
# state: 当前的消息状态对象，包含上下文信息， 封装好了后续用到
def intent_router(state: MessagesState):
    """交通警察逻辑，根据 route 字段决定流程分支"""
    # 获取 route 字段，默认为 business
    route = getattr(state, "route", "business") or "business"
    # 如果 route 是 chat，流程直接结束
    if route == "chat":
        return END
    # 如果 route 是 meta，进入 SQL 生成节点
    if route == "meta":
        return "generate_sql"
    # 如果 route 是 analysis，进入 root cause analysis 子图
    if route == "analysis":
        return "rca_subgraph"
    # 其他情况（默认 business），进入数据新鲜度检查节点
    return "check_freshness"


def build_graph():
    # 1. 初始化“接力棒”：告诉图所有节点都共享 MessagesState 这个账本
    builder = StateGraph(MessagesState)

    # --- 步骤 A：注册节点 (把探员领进办公室) ---
    builder.add_node("intent", intent_node)  # 前台：负责分流
    builder.add_node("check_freshness", check_data_freshness_node)  # 哨兵：看数据新旧
    builder.add_node("generate_sql", generate_sql_node)  # 大脑：写 SQL

    # ToolNode 是官方提供的特殊节点，专门用来执行被 bind 的工具（如 execute_sql）
    # 这是 LangGraph 最强大的地方，它允许你把非标准函数也包装成节点
    builder.add_node("tools", ToolNode([execute_sql]))

    # 挂载子图：把另一个小团队（重案组）作为一个整体节点塞进来
    #这是 LangGraph 最强大的地方，它允许你把非标准函数也包装成节点：
    builder.add_node("rca_subgraph", rca_graph)


    # -------------- 步骤 B：布置走廊 (连线逻辑) ----------------
    # 入口：程序一启动，必先经过“前台”
    builder.add_edge(START, "intent")

    # 条件分支：前台听完后，根据 intent_router 的判断去不同的地方
    builder.add_conditional_edges(
        "intent",
        intent_router,  # 这是一个逻辑函数，返回字符串
        {
            END: END,  # 闲聊就直接结束
            "generate_sql": "generate_sql",  # 查数据去大脑节点
            "check_freshness": "check_freshness",  # 查水位去哨兵节点
            "rca_subgraph": "rca_subgraph"  # 深度分析去重案组
        }
    )

    # 哨兵查完水位后，必须再去写 SQL（因为查水位通常是为了更好地写查询语句）
    builder.add_edge("check_freshness", "generate_sql")

    # 重案组分析完后，直接结案归档
    builder.add_edge("rca_subgraph", END)


    # --- 步骤 C：核心循环 (ReAct 模式的精髓) ---
    # 大脑写完 SQL 后，不一定直接结束，要看它是否想调用工具
    # tools_condition 会检查 AI 是否发出了 tool_calls
    builder.add_conditional_edges(
        "generate_sql",
        tools_condition,
        {
            "tools": "tools",  # 如果 AI 要查数据库，去 tools 节点
            END: END  # 如果 AI 觉得查完了，直接回复用户并结束
        }
    )

    # 🚩 重点：工具执行完后，必须回到大脑！
    # 这样大脑才能看到 SQL 执行的结果，如果报错了，大脑可以根据报错重新写 SQL
    builder.add_edge("tools", "generate_sql")

    # --- 步骤 D：HITL 配置 (Human-in-the-Loop) ---
    # MemorySaver 是内存级 checkpointer，它让图在每一步后都能保存快照
    # 这是实现"物理打断"和"状态恢复"的基础设施
    memory = MemorySaver()

    # 最后，把这张蓝图"编译"成一个可执行的可操作对象
    # checkpointer=memory：开启持久化，每步执行后保存状态快照。是每个node的粒度
    # interrupt_before=["tools"]：在 tools 节点执行前强制挂起，等待人工确认或修改
    return builder.compile(checkpointer=memory, interrupt_before=["tools"])
    # return builder.compile(checkpointer=memory)
    # 之前是return builder.compile() 现在加了checkpointer=memory, interrupt_before=["tools"]，
    # 实现了在tools节点执行前强制挂起，等待人工确认或修改的功能。
