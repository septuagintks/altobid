"""本地推理服务：Flask + Qwen2.5-VL。

接收油猴脚本送来的「题干 + base64 图片」，本地读图作答，返回纯答案。
仅绑定 127.0.0.1，无鉴权，切勿对外暴露。

启动：python -m altobid.server
接口：
  POST /solve   {"image": "<base64|dataURL>", "prompt": "<题干或空>"}
                -> {"answer": "...", "raw": "...", "latency_ms": N}
  GET  /health  -> {"ready": bool, "device": "cuda|cpu|dummy"}
"""
from __future__ import annotations

import base64
import binascii
import io
import time

from flask import Flask, jsonify, request
from PIL import Image, UnidentifiedImageError

from . import get_logger, setup_logging
from .config import Config
from .engine import InferenceEngine
from .postprocess import PostProcessor
from .preprocess import Preprocessor

log = get_logger("server")

app = Flask(__name__)

# 模块级组件（在 main() 里初始化，避免 import 即加载模型）
_engine: InferenceEngine | None = None
_preprocessor: Preprocessor | None = None
_postprocessor: PostProcessor | None = None


def _decode_image(data_uri: str) -> Image.Image:
    """base64 或 dataURL（data:image/png;base64,xxx）-> PIL Image。"""
    b64 = data_uri.split(",", 1)[-1]  # 容忍 dataURL 前缀
    raw = base64.b64decode(b64, validate=False)
    return Image.open(io.BytesIO(raw))


@app.post("/solve")
def solve():
    assert _engine and _preprocessor and _postprocessor  # main() 已初始化
    data = request.get_json(silent=True)
    if not data or "image" not in data:
        return jsonify(error="缺少 image 字段"), 400

    try:
        image = _decode_image(data["image"])
    except (binascii.Error, ValueError, UnidentifiedImageError, OSError) as e:
        log.warning("图片解码失败: %s", e)
        return jsonify(error=f"图片解码失败: {e}"), 400

    prompt = (data.get("prompt") or "").strip()

    t0 = time.perf_counter()
    try:
        image = _preprocessor.process(image)
        raw = _engine.infer(image, prompt or None)
        answer = _postprocessor.clean(raw)
    except Exception as e:  # 推理异常不应崩服务
        log.error("推理失败: %s", e, exc_info=True)
        return jsonify(error=f"推理失败: {e}"), 500

    latency_ms = round((time.perf_counter() - t0) * 1000)
    log.info(
        "solve prompt=%r -> answer=%r (%dms)", prompt or "(无)", answer, latency_ms
    )
    return jsonify(answer=answer, raw=raw, latency_ms=latency_ms)


@app.get("/health")
def health():
    ready = _engine is not None and _engine.device is not None
    device = _engine.device if _engine else None
    return jsonify(ready=ready, device=device)


def _build_engine() -> InferenceEngine:
    m = Config.model
    return InferenceEngine(
        model_path=m.path,
        dtype=m.dtype,
        quantization=m.get("quantization", "none"),
        max_new_tokens=m.max_new_tokens,
        temperature=m.temperature,
        top_p=m.top_p,
        min_pixels=Config.preprocess.min_pixels,
        max_pixels=Config.preprocess.max_pixels,
        system_prompt=m.system_prompt,
        user_prompt=m.user_prompt,
    )


def main() -> int:
    global _engine, _preprocessor, _postprocessor

    setup_logging(level=Config.logging.level, log_file=Config.logging.file)
    log.info("altobid 推理服务启动，加载模型（可能需要数秒）...")

    _engine = _build_engine()
    _preprocessor = Preprocessor(
        min_pixels=Config.preprocess.min_pixels,
        max_pixels=Config.preprocess.max_pixels,
    )
    _postprocessor = PostProcessor()

    host = Config.server.host
    port = Config.server.port
    if host not in ("127.0.0.1", "localhost", "::1"):
        log.warning("host=%s 非本机地址，服务无鉴权，请勿对外暴露！", host)

    log.info("模型就绪 (device=%s)，监听 http://%s:%s", _engine.device, host, port)
    app.run(host=host, port=port, threaded=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
