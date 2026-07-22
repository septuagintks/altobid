# altobid

本地部署的多模态验证码解答工具。用户手动框选屏幕区域，工具通过 `mss` 持续截图，
经变化检测与 ROI resize 后，仅将「发生变化的画面」输入本地 Qwen2.5-VL-3B-Instruct 模型，
解答小学题类型（简单算式）的图形验证码。

- 完全本地推理，不上传任何图像
- 变化检测 + 防抖，避免对同一帧重复推理
- 推理框架：Transformers + Flash Attention 2（缺失时回退 `sdpa`）

## 快速开始

### 环境要求

- Python 3.10 ~ 3.12（**重要**：PyTorch/Transformers 尚不支持 3.13+）
- CUDA 12.1+ / ROCm 6.0+（推理约占 3-7GB 显存，取决于量化方式）
- Windows / Linux / macOS

### 安装

```bash
# 1. 创建虚拟环境
python -m venv .venv
.venv/Scripts/activate   # Windows
# source .venv/bin/activate   # Linux/macOS

# 2. 安装 PyTorch（按 CUDA 版本）
# CUDA 12.4
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu124

# 3. 安装其他依赖
pip install -r requirements.txt

# 4. 下载模型权重（推荐 AWQ 量化，约 3-4GB）
# 自动下载：运行时首次加载会从 Hugging Face 下载到 ~/.cache
# 手动下载（可选）：
# git lfs install
# git clone https://huggingface.co/Qwen/Qwen2.5-VL-3B-Instruct-AWQ
```

### 运行

```bash
# 启动工具
python run.py

# 或直接调用模块
python -m altobid.main
```

**使用流程**：
1. 运行后会弹出全屏半透明覆盖层
2. 鼠标拖拽框选验证码区域（按 Esc 取消）
3. 框选完成后，工具开始监控该区域
4. 检测到验证码变化并稳定后，自动推理并弹窗 + 打印答案
5. 按 Ctrl+C 停止监控

### 配置

创建 `config.local.yaml`（覆盖默认配置）：

```yaml
model:
  path: "Qwen/Qwen2.5-VL-3B-Instruct-AWQ"  # 或本地路径
  dtype: "fp16"  # 或 "bf16"（Ada/Ampere 推荐）
  max_new_tokens: 64

change_detect:
  method: "absdiff"  # 或 "phash"
  change_threshold: 0.02
  stable_frames: 3
  cooldown: 2.0

output:
  show_window: true  # 是否弹窗显示答案
  window_duration: 3000  # 弹窗持续时间（毫秒）
```

## 测试

```bash
pytest tests/ -v
```

## 文档

- 架构设计：[docs/architecture.md](docs/architecture.md)
- 开发步骤：[docs/development.md](docs/development.md)

## 免责声明

本工具仅用于本人拥有合法授权的场景（如自动化测试、辅助学习）。
请勿用于绕过他人系统的安全机制。
