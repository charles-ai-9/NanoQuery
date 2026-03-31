from typing import Annotated, TypedDict, List
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages

class MessagesState(TypedDict):
    # add_messages 会让新消息自动追加到列表末尾，而不是覆盖
    messages: Annotated[List[BaseMessage], add_messages]
    route: str           # 路由标签：chat, meta, business, analysis
    data_freshness: str  # 数据水位日期
    sql_result: str      # 给子图用的输入数据
    analysis: str        # 子图返回的分析结论