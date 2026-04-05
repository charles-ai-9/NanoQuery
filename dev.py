"""
dev.py - NanoQuery 本地开发服务器启动脚本

用法：
    nano_query_env/bin/python dev.py

等同于 `langgraph dev`，但额外设置了：
- server_level="ERROR"：屏蔽 /ok 404 的 warning 刷屏
- LANGGRAPH_NO_VERSION_CHECK=1：关闭版本检查提示
"""
import os
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).parent.absolute()
sys.path.insert(0, str(ROOT_DIR))

os.environ["LANGGRAPH_NO_VERSION_CHECK"] = "1"
os.environ["PYTHONIOENCODING"] = "utf-8"

from langgraph_api.cli import run_server

run_server(
    host="127.0.0.1",
    port=None,
    reload=False,
    env_file=str(ROOT_DIR / ".env"),
    graphs={"agent": "./src/agent/graph.py:build_graph"},
    server_level="ERROR",
    open_browser=False,
)



