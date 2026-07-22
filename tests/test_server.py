"""推理服务测试（假推理模式，无需 torch/权重）。"""
import base64
import io

import pytest
from PIL import Image

from altobid import server
from altobid.engine import InferenceEngine
from altobid.postprocess import PostProcessor
from altobid.preprocess import Preprocessor


def _png_b64(as_data_uri: bool = False) -> str:
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), (255, 255, 255)).save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()
    return f"data:image/png;base64,{b64}" if as_data_uri else b64


@pytest.fixture
def client(tmp_path):
    """装配假推理引擎 + Flask 测试客户端。"""
    server._engine = InferenceEngine(str(tmp_path / "nonexistent"))  # dummy 模式
    server._preprocessor = Preprocessor()
    server._postprocessor = PostProcessor()
    server.app.config.update(TESTING=True)
    return server.app.test_client()


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ready"] is True
    assert body["device"] == "dummy"


def test_solve_plain_base64(client):
    resp = client.post("/solve", json={"image": _png_b64(), "prompt": ""})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["answer"] == "42"  # 假推理返回占位
    assert "latency_ms" in body


def test_solve_data_uri_with_prompt(client):
    resp = client.post(
        "/solve",
        json={"image": _png_b64(as_data_uri=True), "prompt": "请输入四位图形校验码"},
    )
    assert resp.status_code == 200
    assert resp.get_json()["answer"] == "42"


def test_solve_missing_image(client):
    resp = client.post("/solve", json={"prompt": "x"})
    assert resp.status_code == 400
    assert "error" in resp.get_json()


def test_solve_bad_image(client):
    resp = client.post("/solve", json={"image": "not-valid-base64-image!!!"})
    assert resp.status_code == 400
    assert "error" in resp.get_json()
