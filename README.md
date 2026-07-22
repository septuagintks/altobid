# altobid

本地部署的多模态验证码解答工具。用户手动框选屏幕区域，工具通过 `mss` 持续截图，
经变化检测与 ROI resize 后，仅将「发生变化的画面」输入本地 Qwen2.5-VL-3B-Instruct 模型，
解答小学题类型（简单算式）的图形验证码。

- 完全本地推理，不上传任何图像
- 变化检测 + 防抖，避免对同一帧重复推理
- 推理框架：Transformers + Flash Attention 2（缺失时回退 `sdpa`）

## 快速开始

```bash
# 建议 Python 3.10 ~ 3.12
python -m venv .venv && .venv/Scripts/activate   # Windows
pip install -r requirements.txt
# torch 按 CUDA 版本单独安装，见 https://pytorch.org
python -m altobid.main
```

## 文档

- 架构设计：[docs/architecture.md](docs/architecture.md)

## 免责声明

本工具仅用于本人拥有合法授权的场景（如自动化测试、辅助学习）。
请勿用于绕过他人系统的安全机制。
