#!/usr/bin/env python3
"""把 API Key 从明文 config 迁移到 macOS Keychain。

用法:
    .venv/bin/python3 scripts/migrate_key_to_keyring.py              # 迁移（含读回校验）
    .venv/bin/python3 scripts/migrate_key_to_keyring.py --clean-bak  # 迁移 + 删除含明文密钥的 .bak

迁移后自动清除 config 中的 api_key 字段。

**2026-10-07 存储加固的隐私收口（P-1）**：
1. 写入 Keychain 后必须**读回校验**——写失败/写错值时不许清空 config，
   否则密钥会被静默丢弃（AI 解读突然全挂，且原因难查）；
2. 迁移只处理 config 主文件，`config/agent_llm_config.json.bak` 里往往还有一份
   **明文密钥副本**（历史备份）：脚本会如实报出来，并提示用 `--clean-bak` 删除；
   默认不删——删用户文件需要显式授权（本脚本不替用户做这个决定）。
3. 若还有环境变量（`LLM_API_KEY` 等）或别的导出文件带着密钥，脚本会一并提示。
"""
import argparse
import json
import os
import subprocess
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_FILE = os.path.join(PROJECT_ROOT, "config", "agent_llm_config.json")
KEYRING_SERVICE = "shangzhu-llm"
KEYRING_ACCOUNT = "api_key"

# 密钥优先级顺序见 src/llm_advisor.py：config 单源 → env → Keychain → 空。
# 因此清空 config 的 api_key 后，读取会自然落到 Keychain（无需改优先级语义）。
_ENV_KEYS = ("LLM_API_KEY", "DEEPSEEK_API_KEY", "LONGCAT_API_KEY")


def _keychain_read() -> str:
    """读回 Keychain 里的密钥（校验写入真的成功）。"""
    try:
        out = subprocess.run(
            ["security", "find-generic-password",
             "-s", KEYRING_SERVICE, "-a", KEYRING_ACCOUNT, "-w"],
            check=True, capture_output=True, text=True,
        )
        return out.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""


def _plaintext_key_files() -> list:
    """列出仍带明文密钥的文件（主文件之外的历史副本）。"""
    found = []
    for name in os.listdir(os.path.join(PROJECT_ROOT, "config")):
        if not name.startswith("agent_llm_config.json"):
            continue
        path = os.path.join(PROJECT_ROOT, "config", name)
        if name == os.path.basename(CONFIG_FILE) or not os.path.isfile(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        inner = data.get("config", {}) if isinstance(data, dict) else {}
        if isinstance(inner, dict) and (inner.get("api_key") or "").strip():
            found.append(path)
    return found


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="API Key 明文 → macOS Keychain")
    ap.add_argument("--clean-bak", action="store_true",
                    help="删除含明文密钥的历史副本(.bak 等)——默认只报告，不删")
    args = ap.parse_args(argv)

    if not os.path.isfile(CONFIG_FILE):
        print(f"[migrate] 配置文件不存在: {CONFIG_FILE}")
        return 1

    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    current_key = (cfg.get("config", {}) or {}).get("api_key", "").strip()
    if not current_key:
        print("[migrate] config 中已无明文 api_key（可能已迁移或未配置）")
        return _report_leftovers(args)
    if sys.platform != "darwin":
        print("[migrate] 非 macOS：Keychain 不可用，保持 config 明文（600 权限）。"
              "建议改用环境变量 LLM_API_KEY，或确保该文件不入库/不外拷。")
        return 1

    # 1. 写入 Keychain
    print(f"[migrate] 写入 Keychain (service={KEYRING_SERVICE}, account={KEYRING_ACCOUNT})...")
    try:
        subprocess.run(
            ["security", "add-generic-password",
             "-s", KEYRING_SERVICE, "-a", KEYRING_ACCOUNT,
             "-w", current_key, "-U"],
            check=True, capture_output=True,
        )
    except subprocess.CalledProcessError as e:
        print(f"[migrate] 写入失败: {(e.stderr or b'').decode()}")
        print("[migrate] 未改动 config（明文里仍可用），修好 Keychain 后重跑。")
        return 1

    # 2. 读回校验：写进去的东西必须能读出来、且一致
    readback = _keychain_read()
    if readback != current_key:
        print("[migrate] 读回校验失败：Keychain 里的值与要迁移的密钥不一致——"
              "**未清除** config 中的明文（避免把密钥弄丢）。请排查 Keychain 后重跑。")
        return 1
    print("[migrate] 读回校验通过（Keychain 可取回同一密钥）")

    # 3. 清空 config 中的 api_key（读取顺序会自然落到 Keychain）
    if "api_key" in cfg.get("config", {}):
        del cfg["config"]["api_key"]
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=4)
        os.chmod(CONFIG_FILE, 0o600)
        print("[migrate] config/api_key 已清除（model/base_url 等非密钥字段保留）")

    print("[migrate] 完成 — API Key 现在从 Keychain 读取")
    return _report_leftovers(args)


def _report_leftovers(args) -> int:
    """报出仍携带明文密钥的位置（默认只报告；--clean-bak 时才删历史副本）。"""
    leftovers = _plaintext_key_files()
    env_hits = [k for k in _ENV_KEYS if (os.environ.get(k) or "").strip()]

    if not leftovers and not env_hits:
        print("[migrate] 未发现其它明文密钥位置 ✓")
        return 0

    if leftovers:
        print("[migrate] 仍存在带明文密钥的文件副本：")
        for path in leftovers:
            print(f"           - {path}")
        if args.clean_bak:
            for path in leftovers:
                try:
                    os.unlink(path)
                    print(f"[migrate] 已删除（--clean-bak）: {path}")
                except OSError as e:
                    print(f"[migrate] 删除失败 {path}: {e}")
        else:
            print("[migrate] 默认不删用户文件——确认无误后可用 --clean-bak 删除上述副本")
    if env_hits:
        print(f"[migrate] 环境变量里也有密钥：{', '.join(env_hits)}"
              "（优先级高于 Keychain；若不再需要请从 shell 配置里移除）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
