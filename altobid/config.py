"""配置加载。

读取 config/default.yaml，并用可选的 config/local.yaml 深度覆盖。
返回支持点号访问的配置对象：Config.model.path。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from . import PROJECT_ROOT

_DEFAULT_PATH = PROJECT_ROOT / "config" / "default.yaml"
_LOCAL_PATH = PROJECT_ROOT / "config" / "local.yaml"


class ConfigNode:
    """把嵌套 dict 包装成可点号访问的只读节点。

    未知键访问抛 AttributeError，避免拼写错误静默返回 None。
    仍保留 dict 式访问与 .get() 以便动态取值。
    """

    def __init__(self, data: dict[str, Any]):
        self._data = data

    def __getattr__(self, name: str) -> Any:
        # __getattr__ 仅在常规属性查找失败时触发
        try:
            value = self._data[name]
        except KeyError as exc:
            raise AttributeError(
                f"配置项 '{name}' 不存在。可用键: {list(self._data)}"
            ) from exc
        return ConfigNode(value) if isinstance(value, dict) else value

    def __getitem__(self, key: str) -> Any:
        value = self._data[key]
        return ConfigNode(value) if isinstance(value, dict) else value

    def get(self, key: str, default: Any = None) -> Any:
        value = self._data.get(key, default)
        return ConfigNode(value) if isinstance(value, dict) else value

    def to_dict(self) -> dict[str, Any]:
        return self._data

    def __contains__(self, key: str) -> bool:
        return key in self._data

    def __repr__(self) -> str:
        return f"ConfigNode({self._data!r})"


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """把 override 深度合并进 base 的副本并返回。"""
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _resolve_path(value: str) -> str:
    """把配置里的相对路径转为相对项目根的绝对路径；空值原样返回。"""
    if not value:
        return value
    p = Path(value)
    if not p.is_absolute():
        p = PROJECT_ROOT / p
    return str(p)


def load_config(
    default_path: Path = _DEFAULT_PATH, local_path: Path = _LOCAL_PATH
) -> ConfigNode:
    """加载并合并配置，返回 ConfigNode。"""
    if not default_path.exists():
        raise FileNotFoundError(f"默认配置缺失: {default_path}")

    with open(default_path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    if local_path.exists():
        with open(local_path, encoding="utf-8") as f:
            local_data = yaml.safe_load(f) or {}
        data = _deep_merge(data, local_data)

    # 规范化已知的路径型配置项
    if "model" in data and isinstance(data["model"], dict):
        data["model"]["path"] = _resolve_path(data["model"].get("path", ""))
    if "logging" in data and isinstance(data["logging"], dict):
        data["logging"]["file"] = _resolve_path(data["logging"].get("file", ""))
    if "debug" in data and isinstance(data["debug"], dict):
        data["debug"]["frames_dir"] = _resolve_path(data["debug"].get("frames_dir", ""))

    return ConfigNode(data)


# 模块级单例，导入即加载
Config: ConfigNode = load_config()
