from typing import Annotated, List
from pydantic import BaseModel, Field
from langchain_core.messages import BaseMessage
from langgraph.graph import add_messages


# 继承 BaseModel，开启“严苛的入职体检”模式
class MessagesState(BaseModel):
    # add_messages 依然保留它的魔法，负责智能拼接和覆盖
    messages: Annotated[List[BaseMessage], add_messages] = Field(default_factory=list)

    # 严格规定这些字段必须是字符串，并且给了默认值防止空指针报错
    route: str = Field(default="", description="路由标签：chat, meta, business, analysis")
    data_freshness: str = Field(default="", description="数据水位日期")
    sql_result: str = Field(default="", description="给子图用的输入数据")
    analysis: str = Field(default="", description="子图返回的分析结论")

    # 加一个专用于测试“体检”的危险字段：
    # risk_score: float = Field(default=0.0, description="风控危险指数，必须是浮点数")