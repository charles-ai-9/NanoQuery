import sqlite3
import os
import asyncio  # 🌟 必须导入
from pathlib import Path
from langchain_core.tools import tool



# 自动定位项目根目录下的 data/mock_data.db
DB_PATH = Path(__file__).parent.parent.parent / "data" / "mock_data.db"


# 💡 定义一个纯同步的逻辑函数，负责干累活
def _run_sql(query: str) -> str:
    try:
        # 1. 确保目录存在 (这就是之前报错的根源)
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)

        # 2. 执行数据库操作
        with sqlite3.connect(str(DB_PATH)) as conn:
            cursor = conn.cursor()
            cursor.execute(query)
            rows = cursor.fetchall()

            if not rows:
                return "查询成功，但结果为空。"

            # 获取表头
            columns = [desc[0] for desc in cursor.description]
            header = " | ".join(columns)
            body = "\n".join(" | ".join(str(cell) for cell in row) for row in rows)
            return f"{header}\n{'-' * len(header)}\n{body}"
    except Exception as e:
        return f"ERROR: SQL 执行失败: {str(e)}"


@tool
async def execute_sql(query: str) -> str:
    """
    在 mock_data.db 上执行只读 SELECT SQL 查询并返回结果。
    参数 query: 完整的 SQL 查询语句。
    """
    # 🌟 核心魔法：使用 to_thread 异步化，完美绕过 Studio 的阻塞检查
    return await asyncio.to_thread(_run_sql, query)


@tool
def search_knowledge_base(query: str) -> str:
    """
    当用户询问金融风控专业术语（如 DPD, M1, M2）、催收政策、内部操作手册、
    公司规章制度或业务逻辑时，请务必调用此工具。
    输入应该是一个具体的业务搜索问题，例如 "M1级别的催收惩罚策略是什么？" 或 "DPD的定义"。
    """
    from src.agent.nodes import get_kb_instance  # 延迟导入，避免循环依赖
    print(f"\n[Agent 动作] 🕵️‍♂️ 正在翻阅内部风控手册，检索: {query}...")
    result = get_kb_instance().query(query)
    return result
