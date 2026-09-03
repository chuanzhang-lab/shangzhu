#!/usr/bin/env python3
"""把 API Key 从明文 config 迁移到 macOS Keyring。

用法: .venv/bin/python scripts/migrate_key_to_keyring.py
迁移后自动清除 config 中的 api_key 字段。
"""
import json
import os
import subprocess
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_FILE = os.path.join(PROJECT_ROOT, "config", "agent_llm_config.json")
KEYRING_SERVICE = "shangzhu-llm"
KEYRING_ACCOUNT = "api_key"


def main():
    # 1. 读取现有 api_key
    if not os.path.isfile(CONFIG_FILE):
        print(f"[migrate] 配置文件不存在: {CONFIG_FILE}")
        sys.exit(1)

    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    current_key = (cfg.get("config", {}) or {}).get("api_key", "").strip()
    if not current_key:
        print("[migrate] 未找到明文 api_key，可能已迁移或未配置")
        return

    # 2. 写入 macOS Keyring
    print(f"[migrate] 写入 Keychain (service={KEYRING_SERVICE}, account={KEYRING_ACCOUNT})...")
    try:
        subprocess.run(
            ["security", "add-generic-password",
             "-s", KEYRING_SERVICE, "-a", KEYRING_ACCOUNT,
             "-w", current_key, "-U"],
            check=True, capture_output=True,
        )
        print("[migrate] Key 已写入 Keychain")
    except subprocess.CalledProcessError as e:
        print(f"[migrate] 写入失败: {e.stderr.decode()}")
        sys.exit(1)

    # 3. 清除 config 中的 api_key
    if "api_key" in cfg.get("config", {}):
        del cfg["config"]["api_key"]
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=4)
        print("[migrate] config/api_key 已清除")

    print("[migrate] 完成 — API Key 现在从 Keychain 读取")


if __name__ == "__main__":
    main()
