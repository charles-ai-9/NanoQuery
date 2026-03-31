import sqlite3
import os
from pathlib import Path
from langchain_core.tools import tool

# 自动定位项目根目录下的 data/mock_data.db
DB_PATH = Path(__file__).parent.parent.parent / "data" / "mock_data.db"


@tool
async def execute_sql(query: str) -> str:
    """
    在 mock_data.db 上执行只读 SELECT SQL 查询并返回结果。
    参数 query: 完整的 SQL 查询语句。
    """
    try:
        # 确保目录存在
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(DB_PATH))
        cursor = conn.cursor()
        cursor.execute(query)
        rows = cursor.fetchall()

        if not rows:
            return "查询成功，但结果为空。"

        # 获取表头
        columns = [desc[0] for desc in cursor.description]
        header = " | ".join(columns)
        body = "\n".join(" | ".join(str(cell) for cell in row) for row in rows)
        conn.close()
        return f"{header}\n{'-' * len(header)}\n{body}"
    except Exception as e:
        return f"ERROR: SQL 执行失败: {str(e)}"