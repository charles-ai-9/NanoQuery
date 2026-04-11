import logging
from langchain_core.messages import AIMessage, SystemMessage, HumanMessage

# 🎧 核心新增：引入 RunnableConfig (隐形耳麦) 和 Command (瞬间转移)
from langchain_core.runnables.config import RunnableConfig
from langgraph.types import Command

from .state import MessagesState
from src.tools.sql_tools import execute_sql
from functools import lru_cache
from src.core.llm_client import get_llm
from langgraph.store.base import BaseStore  # 用于类型提示
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

llm = None
llm_with_tools = None


@lru_cache(maxsize=1)
def get_llm_with_tools():
    """获取挂载了工具的大模型单例实例"""
    _llm = get_llm()
    if _llm is None:
        raise ValueError("❌ 大模型初始化失败，请检查环境变量配置！")
    return _llm.bind_tools([execute_sql])


def initialize_llm(llm_instance):
    """兼容旧接口：初始化全局 llm 和 llm_with_tools"""
    global llm, llm_with_tools
    llm = llm_instance
    llm_with_tools = llm.bind_tools([execute_sql])


# 🎧 改造点 1：给前台节点戴上隐形耳麦 (加入 config 参数)
from langchain_core.runnables.config import RunnableConfig
from langgraph.types import Command  # 依然引入，留作教学演示


# 🧠 【核心新增】：定义大模型强制输出的情报模具 (Pydantic Schema)
class UserMemory(BaseModel):
    has_preference: bool = Field(description="用户是否在这句话中明确表达了个人喜好、习惯、身份或人物特征？")
    preference_content: str = Field(description="如果表达了特征，请提取具体内容(精简为短语，如'喜欢喝咖啡'、'我是审计部的')；如果没有，返回空字符串。")

# 在函数参数里加上 store: BaseStore，向系统申请访问情报局的权限
async def intent_node(state: MessagesState, config: RunnableConfig, store: BaseStore):
    """
    【前台探员】：负责意图识别与流量调度，并搭载 LLM 智能记忆提取功能。
    """
    user_name = config.get("configurable", {}).get("user_name", "Jack")
    user_role = config.get("configurable", {}).get("role", "admin")

    if not state.messages:
        logger.warning("intent_node: 消息列表为空，直接路由到 chat")
        return {"route": "chat"}

    last_msg_content = state.messages[-1].content.strip()

    _llm = get_llm()
    if _llm is None:
        error_msg = "❌ 大模型初始化失败，请检查 .env 文件配置。"
        logger.error("intent_node: %s", error_msg)
        return {"messages": [AIMessage(content=error_msg)], "route": "chat"}

    # =====================================================================
    # 🕵️‍♂️ 跨 Session 侦查 (Store API) + LLM 智能提取 (Structured Output)
    # =====================================================================
    namespace = ("user_profiles", user_name)

    # 1. 召唤一个专门负责提取记忆的 AI 分身，套上 Pydantic 模具
    memory_extractor = _llm.with_structured_output(UserMemory)

    try:
        # 2. 审问这句话，强行要求输出 JSON
        memory_result = await memory_extractor.ainvoke([
            SystemMessage(
                content="你是一个心理分析师，任务是从用户的日常对话中提取他们的长期偏好或个人特征。如果没有明确特征，不要凭空捏造。"),
            HumanMessage(content=last_msg_content)
        ])

        # 3. 智能判断是否需要写入 SQLite Store (彻底消灭 if "我喜欢")
        # 先确认大模型没有返回 None，再去读里面的属性
        if memory_result and memory_result.has_preference and memory_result.preference_content:
            await store.aput(namespace, "preference", {"likes": memory_result.preference_content})
            logger.info(f"💾 [Store API]: 智能提取并持久化特征 -> [{memory_result.preference_content}]")
    except Exception as e:
        logger.warning(f"记忆提取环节发生异常 (非致命，跳过): {e}")

    # 4. 读取最新情报，随时准备套近乎
    profile = await store.aget(namespace, "preference")
    known_preference = profile.value.get("likes") if profile else None
    # =====================================================================

    # ── 物理拦截 ────────────────────────────
    META_KEYWORDS = ["表", "字段", "结构", "元数据", "有哪些表", "schema"]
    ANALYSIS_KEYWORDS = ["为什么", "原因", "分析", "归因", "排查"]

    for kw in META_KEYWORDS:
        if kw in last_msg_content:
            logger.info("intent_node: 关键字[%s]触发物理拦截 → meta", kw)
            return {"messages": [AIMessage(content="【META】")], "route": "meta"}

    for kw in ANALYSIS_KEYWORDS:
        if kw in last_msg_content:
            logger.info("intent_node: 关键字[%s]触发物理拦截 → analysis", kw)
            return {"messages": [AIMessage(content="【ANALYSIS】")], "route": "analysis"}

    # ── LLM 意图分类 ────────────────────────────────
    system_prompt = """你是一个极其严谨的金融数据库侦探前台。
    分类准则：【META】、【BUSINESS】、【ANALYSIS】、【CHAT】。
    回复格式要求：如果是 CHAT，回复 【CHAT】+幽默回复；其他只回复单单词标签。"""

    res = await _llm.ainvoke([SystemMessage(content=system_prompt), HumanMessage(content=last_msg_content)])
    res_text = res.content.upper()
    logger.info("intent_node: LLM 分类结果 → %s", res_text[:50])

    if "CHAT" in res_text:
        reply = res.content.replace("【CHAT】", "").strip()

        # 融合长期记忆进行回复
        if known_preference:
            personalized_reply = f"[权限: {user_role}] 敬礼！{user_name}！我知道您【{known_preference}】！{reply}"
        else:
            personalized_reply = f"[权限: {user_role}] 敬礼！{user_name}！{reply}"

        return {"messages": [AIMessage(content=personalized_reply)], "route": "chat"}

    elif "META" in res_text:
        return {"messages": [res], "route": "meta"}
    elif "ANALYSIS" in res_text:
        return {"messages": [res], "route": "analysis"}
    else:
        return {"messages": [res], "route": "business"}


async def check_data_freshness_node(state: MessagesState):
    """【哨兵探员】：负责环境感知。"""
    date = "2024-12-23"
    return {"messages": [SystemMessage(content=f"当前数据截止到 {date}。")], "data_freshness": date}


# 🎧 改造点 4：给核心大脑戴上隐形耳麦
async def generate_sql_node(state: MessagesState, config: RunnableConfig):
    """
    【核心大脑】：ReAct 思想的物理载体。
    """
    _llm_with_tools = get_llm_with_tools()

    # 🎧 探听耳麦情报：获取权限级别，用于 SQL 生成拦截
    user_name = config.get("configurable", {}).get("user_name", "未知员工")
    user_role = config.get("configurable", {}).get("role", "user")

    messages = state.messages
    last_msg = messages[-1] if messages else None
    last_msg_content = last_msg.content if last_msg else ""

    correction_prompt = ""

    if isinstance(last_msg, HumanMessage) and len(messages) > 1:
        correction_prompt = (
            "\n[👨‍💼 人类导师反馈]\n"
            f"反馈内容：{last_msg_content}\n"
            "请仔细阅读上述人类反馈修正 SQL。如果提供了完整 SQL 则原封不动执行。"
        )
    elif "ERROR" in last_msg_content:
        correction_prompt = (
            "\n[🚩 紧急纠错指令]\n"
            f"错误信息为: {last_msg_content}\n"
            "请分析原因修正 SQL 后再次调用。"
        )

    # ✨ 改造点 5：权限动态注入！根据不同身份给予不同的 Prompt 紧箍咒
    role_instruction = ""
    if user_role == "admin":
        role_instruction = f"3. 【权限最高级】：当前操作者是 {user_name} (Admin)，拥有所有数据库表的无限制查询权限。"
    else:
        # 如果是普通用户，严禁查询敏感数据！
        role_instruction = f"3. 【权限受限】：当前操作者是 {user_name} ({user_role})，生成的 SQL 必须严格限制范围，严禁查询薪酬、密码等高管敏感表！"

    sys_instruction = SystemMessage(content=(
        "你是一个严谨的金融 SQL 侦探。\n"
        "1. 严禁幻觉：必须且只能使用 `execute_sql` 获取数据。\n"
        "2. 命名规范：严格遵守数据库表名，SQLite 中不要随意加复数 's'。\n"
        f"{role_instruction}\n"  # 👈 注入动态权限
        f"{correction_prompt}"
    ))

    input_msgs = [sys_instruction] + messages[-10:]

    try:
        # 顺便在日志里打印一下当前执行权限，方便排错
        logger.info(f"generate_sql_node: 正在调度 AI... [当前权限: {user_role}]")
        response = await _llm_with_tools.ainvoke(input_msgs)
        return {"messages": [response]}
    except Exception as e:
        logger.error("大脑节点崩溃: %s", str(e))
        return {"messages": [AIMessage(content=f"❌ 侦探大脑思考时发生意外: {str(e)}")]}