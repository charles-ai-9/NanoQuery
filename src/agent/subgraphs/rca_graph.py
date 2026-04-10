import os
from typing import Dict, Any
# 🚩 改造点 1：干掉 TypedDict，换成 Pydantic 的 BaseModel 和 Field
from pydantic import BaseModel, Field
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from src.core.llm_client import get_llm


# --- 1. 定义子图专属状态 (严苛的入职体检) ---
# 🚩 改造点 2：继承 BaseModel，并给字段加上默认值防空指针
class RcaState(BaseModel):
    sql_result: str = Field(default="", description="传入的 SQL 查询结果")
    analysis: str = Field(default="", description="输出的归因分析报告")


# --- 2. 探员节点逻辑 ---
async def rca_analyse_node(state: RcaState) -> Dict[str, Any]:
    _llm = get_llm()

    # 🚩 改造点 3：抛弃 state.get()，直接使用面向对象的点语法 state.sql_result
    sql_data = state.sql_result.strip()

    # 增加一个防御逻辑：如果数据太长，先进行简单的截断或提示
    if len(sql_data) > 5000:
        sql_data = sql_data[:2500] + "\n...[数据过长已截断]...\n" + sql_data[-2500:]

    if not sql_data or "空" in sql_data:
        return {"analysis": "未发现异常数据，无需归因。"}

    # 在 rca_analyse_node 中加强提示词
    messages = [
        SystemMessage(content=(
            "你是一名金融风控专家。当用户要求'核查'异常数据时：\n"
            "1. 首先锁定异常发生的具体日期和维度。\n"
            "2. 必须生成 SQL 来查询该异常点背后的【明细数据】（如具体流水），而不是去看无关的表。\n"
            "3. 对比该异常点与前后日期的分布差异。"
        )),
        HumanMessage(content=f"用户要求核查异常，已知前置汇总数据为：{sql_data}。请开始下钻分析。")
    ]

    response = await _llm.ainvoke(messages)

    # 💡 架构师笔记：返回值依然是纯字典，LangGraph 会自动帮你塞进 RcaState 这个 BaseModel 里做校验
    return {"analysis": response.content}


# --- 3. 组装子图 ---
def build_rca_subgraph() -> CompiledStateGraph:
    sg = StateGraph(RcaState)
    sg.add_node("rca_analyse_node", rca_analyse_node)
    sg.set_entry_point("rca_analyse_node")  # 替代 START 更加直观
    sg.add_edge("rca_analyse_node", END)
    return sg.compile()


# 导出工牌
rca_graph = build_rca_subgraph()