#!/usr/bin/env python3
"""
本地冒烟测试 — 构建 Coze Agent 并跑一条示例对话。

注意：本项目的 Agent 实际使用 DeepSeek（见 config/agent_llm_config.json
与 src/agents/agent.py），与本地独立服务 web_server.py 是两条不同路径。
本脚本只测 Coze Agent 路径，且需要在环境变量中提供 DEEPSEEK_API_KEY。

用法: cd <项目根> && .venv/bin/python local_test.py
"""

import sys
import os
import json

# 设置工作目录（本脚本位于仓库根目录）
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
WORK_DIR = SCRIPT_DIR
SRC_DIR = os.path.join(WORK_DIR, "src")

# 设置环境变量
os.environ["COZE_WORKSPACE_PATH"] = WORK_DIR

# 添加 src 到 Python 路径
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

# 切换到 src 目录（工具模块相对导入需要）
os.chdir(SRC_DIR)

print("=" * 60)
print("创业者商业建模工作台 — 本地 Agent 冒烟测试")
print("=" * 60)
print()

# 测试 1: 导入检查
print("[1/3] 检查依赖导入...")
try:
    from langchain_openai import ChatOpenAI
    print("  ✓ ChatOpenAI")
except ImportError as e:
    print(f"  ✗ ChatOpenAI: {e}")
    sys.exit(1)

try:
    from langgraph.graph import MessagesState
    print("  ✓ LangGraph")
except ImportError as e:
    print(f"  ✗ LangGraph: {e}")
    sys.exit(1)

# 读取真实配置（避免硬编码误导）
config_path = os.path.join(WORK_DIR, "config", "agent_llm_config.json")
try:
    with open(config_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    model = cfg["config"].get("model", "unknown")
    print(f"  ✓ 配置: {config_path}")
except Exception as e:
    print(f"  ✗ 读取配置失败: {e}")
    sys.exit(1)

# 检查可选依赖
try:
    import openpyxl
    print("  ✓ openpyxl (本地 Excel 生成)")
except ImportError:
    print("  ○ openpyxl 未安装 (Excel 生成将不可用)")

try:
    from coze_coding_dev_sdk import SearchClient
    print("  ✓ Coze SDK (联网搜索)")
except ImportError:
    print("  ○ Coze SDK 未安装 (联网搜索将不可用)")

print()

# 测试 2: Agent 构建
print("[2/3] 构建 Agent...")
try:
    from agents.agent import build_agent
    agent = build_agent()
    print("  ✓ Agent 构建成功")
    print(f"  模型: {model}  (DeepSeek, API: https://api.deepseek.com/v1)")
    if not os.getenv("DEEPSEEK_API_KEY"):
        print("  ⚠ DEEPSEEK_API_KEY 未设置，对话测试将失败（请先 export 密钥）")
except Exception as e:
    print(f"  ✗ Agent 构建失败: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print()

# 测试 3: 简单对话测试
print("[3/3] 测试对话...")
try:
    from langchain_core.messages import HumanMessage

    # 简单测试输入
    test_input = {
        "messages": [HumanMessage(content="开一家咖啡店，月租金15000，员工3人，人均工资5000，每天50杯，均价25元")]
    }

    print("  输入: 开一家咖啡店，月租金15000，员工3人，人均工资5000，每天50杯，均价25元")
    if not os.getenv("DEEPSEEK_API_KEY"):
        print("  跳过：DEEPSEEK_API_KEY 未设置")
    else:
        print("  等待 DeepSeek 响应...")
        print()

        result = agent.invoke(test_input)

        # 提取最后一条消息
        if result and "messages" in result:
            last_msg = result["messages"][-1]
            if hasattr(last_msg, "content"):
                print("  [Agent 输出]")
                print("-" * 40)
                print(last_msg.content[:2000])  # 限制输出长度
                print("-" * 40)
            else:
                print(f"  消息类型: {type(last_msg)}")
        else:
            print(f"  返回: {result}")

    print()
    print("✓ 测试完成！")

except Exception as e:
    print(f"  ✗ 对话测试失败: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print()
print("=" * 60)
