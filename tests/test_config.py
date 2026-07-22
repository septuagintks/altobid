"""配置加载测试。"""
from pathlib import Path

import pytest

from altobid.config import ConfigNode, load_config


def test_load_default():
    cfg = load_config()
    assert cfg.server.host == "127.0.0.1"
    assert cfg.server.port == 8799
    assert cfg.model.max_new_tokens == 64


def test_path_resolved_absolute():
    cfg = load_config()
    assert Path(cfg.model.path).is_absolute()
    assert Path(cfg.logging.file).is_absolute()


def test_dot_access_and_unknown_key_guard():
    cfg = load_config()
    with pytest.raises(AttributeError):
        _ = cfg.model.does_not_exist


def test_deep_merge(tmp_path):
    default = tmp_path / "default.yaml"
    local = tmp_path / "local.yaml"
    default.write_text(
        "model:\n  path: ./m\n  max_new_tokens: 64\ncapture:\n  interval_ms: 200\n",
        encoding="utf-8",
    )
    local.write_text("model:\n  max_new_tokens: 128\n", encoding="utf-8")
    cfg = load_config(default, local)
    # 覆盖生效，其它键保留
    assert cfg.model.max_new_tokens == 128
    assert cfg.capture.interval_ms == 200


def test_confignode_get_and_contains():
    node = ConfigNode({"a": 1, "nested": {"b": 2}})
    assert node.get("a") == 1
    assert node.get("missing", "d") == "d"
    assert "a" in node
    assert node.nested.b == 2
