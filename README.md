# altobid

本地部署的多模态验证码解答工具。用户通过全局快捷键触发框选屏幕区域，工具通过 `mss` 持续截图，
经变化检测与 ROI resize 后，仅将「发生变化的画面」输入本地 Qwen2.5-VL-3B-Instruct 模型，
解答小学题类型（简单算式）的图形验证码。

- 完全本地推理，不上传任何图像
- 变化检测 + 防抖，避免对同一帧重复推理
- NF4 量化（bitsandbytes），仅需 ~2.5GB 显存
- 推理框架：Transformers + Flash Attention 2（缺失时回退 `sdpa`）

## 快速开始

### 环境要求

- Python 3.10 ~ 3.12（**重要**：PyTorch/Transformers 尚不支持 3.13+）
- CUDA 12.1+ / ROCm 6.0+（NF4 量化约 2.5GB 显存，fp16 约 6-8GB）
- Windows / Linux / macOS

### 安装

```bash
# 1. 创建虚拟环境（推荐 Python 3.10-3.12）
python -m venv .venv
.venv/Scripts/activate   # Windows
# source .venv/bin/activate   # Linux/macOS

# 2. 安装 PyTorch（按 CUDA 版本）
# CUDA 12.4
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu124

# 3. 安装其他依赖
pip install -r requirements.txt

# 4. 下载模型权重（首次运行时自动从 Hugging Face 下载到 ~/.cache）
# 手动预下载（可选）：
# git lfs install
# git clone https://huggingface.co/Qwen/Qwen2.5-VL-3B-Instruct
```

### 运行

```bash
# 启动工具（推荐）
python -m altobid.main

# 或使用 run.py（如果存在）
python run.py
```

**使用流程**：

1. **启动**：运行后会加载模型（约 15-20 秒），完成后出现半透明覆盖层
2. **框选**：按 **Ctrl+F1** 触发框选模式，鼠标拖拽框出验证码区域（按 Esc 取消）
3. **监控**：框选完成后，绿色框保留在屏幕上，工具开始监控该区域
4. **调整**：按住 **Ctrl** 取消鼠标穿透，可拖动框体或拖拽四角调整大小
5. **推理**：检测到验证码变化并稳定后，自动推理并弹窗 + 打印答案
6. **停止**：按 **Ctrl+C** 停止程序

### 配置

复制 [config.example.yaml](config.example.yaml) 为 `config/local.yaml`，只写需要覆盖的项即可
（完整默认值见 [config/default.yaml](config/default.yaml)）：

```yaml
model:
  path: Qwen/Qwen2.5-VL-3B-Instruct  # 本地权重目录或 HF 名称
  dtype: fp16          # fp16 / bf16 / fp32
  quantization: nf4    # nf4 / gptq / none（fp16 直接推理）
  max_new_tokens: 64

change_detect:
  method: absdiff      # absdiff / phash
  change_threshold: 0.02
  stable_frames: 3
  cooldown_s: 1.5

output:
  show_window: true    # 是否弹窗显示答案
  window_duration_ms: 3000

debug:
  save_frames: false   # 是否保存推理帧到 debug_frames/
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
