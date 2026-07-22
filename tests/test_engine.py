"""推理引擎测试。

分两层：
1. 假推理模式（无依赖/权重）：验证降级逻辑
2. 真实推理（需要 torch + 权重）：仅在环境具备时运行
"""
import sys
from pathlib import Path

import pytest
from PIL import Image

from altobid.engine import InferenceEngine


@pytest.fixture
def dummy_image():
    """造一张 224x224 RGB 图。"""
    return Image.new("RGB", (224, 224), color=(128, 128, 128))


# ---- 假推理模式测试（总是跑） ----


def test_dummy_mode_when_no_weights(dummy_image, tmp_path):
    """权重路径不存在时降级到假推理。"""
    fake_path = tmp_path / "nonexistent"
    engine = InferenceEngine(str(fake_path))
    assert engine.device == "dummy"
    result = engine.infer(dummy_image)
    assert isinstance(result, str)
    assert result == "42"


def test_infer_accepts_optional_prompt(dummy_image, tmp_path):
    """infer 接受可选题干 prompt，非空/空/None 都不崩。"""
    engine = InferenceEngine(str(tmp_path / "nonexistent"))
    assert engine.infer(dummy_image, "请输入四位图形校验码") == "42"
    assert engine.infer(dummy_image, "") == "42"
    assert engine.infer(dummy_image, None) == "42"


# ---- 真实推理测试（需要 torch + 权重） ----


def _has_torch_and_model():
    """检查是否具备真实推理环境。"""
    try:
        import torch  # noqa: F401
        from transformers import Qwen2VLForConditionalGeneration  # noqa: F401
    except ImportError:
        return False

    from altobid.config import load_config

    cfg = load_config()
    model_path = Path(cfg.model.path)
    if not (model_path.exists() and (model_path / "config.json").exists()):
        return False
    # 权重下载完整才跑（避免下载中途误触发）
    has_weights = any(model_path.glob("*.safetensors")) or (
        model_path / "model.safetensors.index.json"
    ).exists()
    return has_weights


@pytest.mark.skipif(
    not _has_torch_and_model(),
    reason="需要 torch + transformers + 模型权重",
)
def test_real_inference_loads_model(dummy_image):
    """真实环境下能加载模型并推理。"""
    from altobid.config import load_config

    cfg = load_config()
    engine = InferenceEngine(
        cfg.model.path,
        dtype=cfg.model.dtype,
        quantization=cfg.model.get("quantization", "none"),
        max_new_tokens=cfg.model.max_new_tokens,
    )

    assert engine.model is not None
    assert engine.processor is not None
    assert engine.device in ("cuda", "cpu")

    # 推理一张灰图（不期望有意义答案，只验证不崩溃）
    result = engine.infer(dummy_image)
    assert isinstance(result, str)
    assert len(result) > 0


@pytest.mark.skipif(
    not _has_torch_and_model(),
    reason="需要 torch + transformers + 模型权重",
)
def test_custom_prompt_via_constructor(dummy_image):
    """自定义 prompt 通过构造函数传入。"""
    from altobid.config import load_config

    cfg = load_config()
    engine = InferenceEngine(
        cfg.model.path,
        quantization=cfg.model.get("quantization", "none"),
        system_prompt="你是助手。",
        user_prompt="描述这张图片：",
    )
    result = engine.infer(dummy_image)
    assert isinstance(result, str)
