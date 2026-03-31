"""
graph.py - NanoQuery 拓扑升级：支持工具执行循环
"""

from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition
from src.agent.nodes import check_data_freshness_node, generate_sql_node, intent_node
from .state import MessagesState
from src.tools.sql_tools import execute_sql
from src.agent.subgraphs.rca_graph import rca_graph # 确保此导入路径正确

def intent_router(state: MessagesState):
    """交通警察逻辑"""
    route = state.get("route", "business")
    if route == "chat": return END
    if route == "meta": return "generate_sql"
    if route == "analysis": return "rca_subgraph"
    return "check_freshness"

def build_graph():
    builder = StateGraph(MessagesState)

    # 注册节点
    builder.add_node("intent", intent_node)
    builder.add_node("check_freshness", check_data_freshness_node)
    builder.add_node("generate_sql", generate_sql_node)
    builder.add_node("tools", ToolNode([execute_sql]))
    builder.add_node("rca_subgraph", rca_graph) # 挂载重案组

    # 连线
    builder.add_edge(START, "intent")
    builder.add_conditional_edges(
        "intent",
        intent_router,
        {END: END, "generate_sql": "generate_sql", "check_freshness": "check_freshness", "rca_subgraph": "rca_subgraph"}
    )
    builder.add_edge("check_freshness", "generate_sql")
    builder.add_edge("rca_subgraph", END) # 分析完直接结案

    builder.add_conditional_edges("generate_sql", tools_condition, {"tools": "tools", END: END})
    builder.add_edge("tools", "generate_sql")

    return builder.compile()