import logging
from langchain_core.messages import AIMessage, SystemMessage, HumanMessage

# 🎧 核心新增：引入 RunnableConfig (隐形耳麦) 和 Command (瞬间转移)
from langchain_core.runnables.config import RunnableConfig
from langgraph.types import Command

from .state import MessagesState
from src.tools.sql_tools import execute_sql
from functools import lru_cache
from src.core.llm_client import get_llm

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
async def intent_node(state: MessagesState, config: RunnableConfig):
    """
    【前台探员】：负责意图识别与流量调度。
    """
    # 🎧 探听耳麦情报：从总局(main.py)传来的 config 中提取身份信息
    user_name = config.get("configurable", {}).get("user_name", "神秘长官")
    user_role = config.get("configurable", {}).get("role", "user")

    # ── 第一道防线：消息为空检查 ──────────────────────────────────────────
    if not state.messages:
        logger.warning("intent_node: 消息列表为空，直接路由到 chat")
        return {"route": "chat"}

    last_msg_content = state.messages[-1].content.strip()

    # ── 第二道防线：关键字物理拦截 ────────────────────────────
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

    # ── 第三道防线：LLM 初始化检查 ─────────────────────────────────────────
    _llm = get_llm()
    if _llm is None:
        error_msg = "❌ 大模型初始化失败，请检查 .env 文件配置。"
        logger.error("intent_node: %s", error_msg)
        return {"messages": [AIMessage(content=error_msg)], "route": "chat"}

    # ── 第四道防线：LLM 意图分类 ────────────────────────────────
    system_prompt = """你是一个极其严谨的金融数据库侦探前台。
    请根据用户的输入进行分类。**严禁**将涉及数据库结构的询问误判为闲聊。

    分类准则：
    1. 【META】：询问数据库结构、元数据等。
    2. 【BUSINESS】：查询具体业务数据、指标等。
    3. 【ANALYSIS】：归因分析，问"为什么"。
    4. 【CHAT】：纯粹打招呼、闲聊。

    回复格式要求：如果是 CHAT，回复 【CHAT】+幽默回复；其他只回复单单词标签。"""

    res = await _llm.ainvoke([SystemMessage(content=system_prompt), HumanMessage(content=last_msg_content)])
    res_text = res.content.upper()
    logger.info("intent_node: LLM 分类结果 → %s", res_text[:50])

    if "CHAT" in res_text:
        # ✨ 改造点 2：使用 config 里的名字进行个性化称呼
        reply = res.content.replace("【CHAT】", "").strip()
        personalized_reply = f"[权限验证通过：{user_role}] 敬礼！{user_name}！{reply}"

        # ✨ 改造点 3：瞬间转移魔法！
        # 如果是闲聊，直接在这里就宣告结案，强制跳到 __end__，不再走任何后续流程
        return Command(
            update={"messages": [AIMessage(content=personalized_reply)], "route": "chat"},
            goto="__end__"
        )
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