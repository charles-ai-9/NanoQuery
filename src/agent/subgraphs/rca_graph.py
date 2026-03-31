"""
rca_graph.py - 重案组（归因分析）子图

【小白学习点】：
1. 独立状态：RcaState 只关心 sql_result 和 analysis，这叫“最小必要原则”。
2. 变量导出：最后的 rca_graph 变量是给主图 import 用的“工牌”。
"""

import os
from typing import Dict, Any
from typing_extensions import TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.language_models.chat_models import BaseChatModel
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph


# --- 1. 定义子图专属的“小工单” ---
class RcaState(TypedDict):
    sql_result: str  # 接收主图传来的查询结果
    analysis: str  # 产出分析报告返回给主图


# --- 2. 构建 LLM 大脑 ---
def _build_llm() -> BaseChatModel:
    """如果有 Key 用真的，没 Key 用 Mock 的，保证程序不崩"""
    if os.environ.get("OPENAI_API_KEY"):
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(model="gpt-4o-mini", temperature=0.3)

    from langchain_core.language_models.fake_chat_models import FakeListChatModel
    return FakeListChatModel(
        responses=[
            "【重案组归因分析】\n检测到贷款申请下降 15%。\n原因：1. 竞品利率下调；2. 信用分准入从 400 提高到了 500；3. 流程耗时增加。"]
    )


_llm = _build_llm()


# --- 3. 探员节点逻辑 ---
async def rca_analyse_node(state: RcaState) -> Dict[str, Any]:
    sql_data = state.get("sql_result", "").strip()
    if not sql_data:
        return {"analysis": "未发现异常数据，无需归因。"}

    messages = [
        SystemMessage(content="你是一名风控专家，请根据数据做归因分析。"),
        HumanMessage(content=f"数据如下：\n{sql_data}")
    ]
    response = await _llm.ainvoke(messages)
    return {"analysis": response.content}


# --- 4. 组装子图 ---
def build_rca_subgraph() -> CompiledStateGraph:
    # 注意：这里我们给 StateGraph 实例起名叫 sg
    sg = StateGraph(RcaState)
    sg.add_node("rca_analyse_node", rca_analyse_node)
    sg.add_edge(START, "rca_analyse_node")
    sg.add_edge("rca_analyse_node", END)
    return sg.compile()


# 🔥 核心修复点：
# 这里的变量名必须叫 rca_graph，因为你在 graph.py 里写的是 from ... import rca_graph
# 而且必须加括号调用函数，拿到编译后的对象
rca_graph = build_rca_subgraph()