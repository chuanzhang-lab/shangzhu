"""配置管理模块 — 原子写 + 校验 + 备份

提供 LLM 配置的读写接口，确保：
1. 写入原子性（临时文件 + os.replace）
2. 写入前校验（JSON 格式 + 必填字段）
3. 写入前备份（.bak 文件）
4. 读取容错（文件损坏时返回默认配置）
"""
import json
import logging
import os
import tempfile
import shutil
import threading
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# 串行化配置的「读-改-写」：save_llm_config 是 load→改→写三步复合操作，
# 并发保存会丢失后写者未见的前写者字段改动（lost update）。
_CONFIG_LOCK = threading.Lock()

# 默认配置（当配置文件不存在或损坏时使用）
_DEFAULT_CONFIG = {
    "config": {
        "model": "deepseek-v4-flash",
        "base_url": "https://api.deepseek.com/v1",
        "api_key": "",
        "temperature": 0.3,
        "timeout": 60,
    }
}

# 必填字段（api_key 可以为空字符串，表示未配置）
_REQUIRED_FIELDS = ["model", "base_url"]

# 字段类型校验
_FIELD_TYPES = {
    "model": str,
    "base_url": str,
    "api_key": str,
    "temperature": (int, float),
    "timeout": (int, float),
}


def _resolve_config_path() -> Path:
    """解析配置文件路径（复用 llm_advisor 的路径逻辑）。"""
    env_ws = os.getenv("COZE_WORKSPACE_PATH", "").strip()
    if env_ws:
        p = Path(env_ws) / "config" / "agent_llm_config.json"
        if p.is_file():
            return p
    repo_root = Path(__file__).resolve().parent.parent
    p = repo_root / "config" / "agent_llm_config.json"
    if p.is_file():
        return p
    # 兜底：返回首选路径
    if env_ws:
        return Path(env_ws) / "config" / "agent_llm_config.json"
    return repo_root / "config" / "agent_llm_config.json"


CONFIG_PATH = _resolve_config_path()


def load() -> dict:
    """加载配置，容错处理。"""
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict) or "config" not in data:
            logger.warning("配置文件格式异常，使用默认配置")
            return _DEFAULT_CONFIG.copy()
        return data
    except FileNotFoundError:
        logger.info("配置文件不存在，使用默认配置: %s", CONFIG_PATH)
        return _DEFAULT_CONFIG.copy()
    except json.JSONDecodeError as e:
        logger.error("配置文件 JSON 解析失败: %s", e)
        return _DEFAULT_CONFIG.copy()
    except Exception as e:
        logger.error("读取配置文件失败: %s", e)
        return _DEFAULT_CONFIG.copy()


def validate(config: dict) -> tuple[bool, str]:
    """校验配置格式。返回 (是否通过, 错误信息)。"""
    if not isinstance(config, dict):
        return False, "配置必须是 JSON 对象"
    
    # 支持两种格式：{"config": {...}} 或直接 {...}
    inner = config.get("config", config)
    if not isinstance(inner, dict):
        return False, "配置内容必须是对象"
    
    # 必填字段检查
    for field in _REQUIRED_FIELDS:
        val = inner.get(field)
        if not val or not str(val).strip():
            return False, f"缺少必填字段: {field}"
    
    # 类型检查
    for field, expected_type in _FIELD_TYPES.items():
        val = inner.get(field)
        if val is not None and not isinstance(val, expected_type):
            return False, f"字段 {field} 类型错误，期望 {expected_type.__name__}"
    
    # URL 格式基础检查
    base_url = inner.get("base_url", "")
    if base_url and not (base_url.startswith("http://") or base_url.startswith("https://")):
        return False, "base_url 必须以 http:// 或 https:// 开头"
    
    return True, ""


def save(config: dict) -> tuple[bool, str]:
    """保存配置（原子写 + 备份）。返回 (是否成功, 错误信息)。"""
    # 校验
    ok, msg = validate(config)
    if not ok:
        return False, msg
    
    # 确保目录存在
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    
    # 备份旧文件
    if CONFIG_PATH.is_file():
        bak_path = CONFIG_PATH.with_suffix(".json.bak")
        try:
            shutil.copy2(str(CONFIG_PATH), str(bak_path))
        except Exception as e:
            logger.warning("备份旧配置失败: %s", e)
    
    # 原子写入：先写临时文件，再 rename
    try:
        fd, tmp_path = tempfile.mkstemp(
            dir=str(CONFIG_PATH.parent),
            prefix=".agent_llm_config_",
            suffix=".tmp",
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, str(CONFIG_PATH))
        except Exception:
            # 清理临时文件
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
    except Exception as e:
        logger.error("保存配置失败: %s", e)
        return False, f"写入失败: {e}"
    
    logger.info("配置已保存: %s", CONFIG_PATH)
    return True, ""


def get_masked() -> dict:
    """获取脱敏后的配置（用于 API 返回）。"""
    config = load()
    inner = config.get("config", {}).copy()
    api_key = inner.get("api_key", "")
    if api_key and len(api_key) > 8:
        inner["api_key"] = api_key[:4] + "*" * (len(api_key) - 8) + api_key[-4:]
    elif api_key:
        inner["api_key"] = "*" * len(api_key)
    return {"config": inner}


def get_llm_config_view() -> dict:
    """获取 LLM 配置的视图（脱敏），供 /settings/llm GET 返回。"""
    return get_masked()


def update_config(mutator) -> dict:
    """锁内原子读-改-写：mutator(inner_dict) 就地修改配置，返回脱敏视图。

    审查修复 F1 补全：save_llm_config 只能串行化「单次保存」，但调用方若
    先 load() 再传回 save_llm_config（锁外读），仍会以过期基底覆盖并发改动。
    需要读-改-写的调用方应改用本函数，把修改逻辑闭包传入，全程持锁。
    """
    with _CONFIG_LOCK:
        config = load()
        inner = config.get("config", {}).copy()
        mutator(inner)
        ok, msg = save({"config": inner})
        if not ok:
            raise ValueError(msg)
        return get_masked()

def save_llm_config(model: str, base_url: str, api_key: str) -> dict:
    """保存 LLM 配置，返回脱敏视图。
    
    参数:
        model: 模型名称
        base_url: API 端点
        api_key: API Key（空串表示不覆盖现有 key）
    
    返回:
        脱敏后的配置视图 dict
    
    异常:
        ValueError: 参数校验失败
    """
    # 读-改-写全程持锁：防止并发保存丢失字段改动（lost update）
    with _CONFIG_LOCK:
        # 读取现有配置
        config = load()
        inner = config.get("config", {}).copy()

        # 更新字段
        inner["model"] = model.strip()
        inner["base_url"] = base_url.strip()
        if api_key:
            inner["api_key"] = api_key.strip()

        # 保存
        ok, msg = save({"config": inner})
        if not ok:
            raise ValueError(msg)

        return get_masked()
