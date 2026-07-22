# altobid 开发步骤文档

| 项目 | altobid |
| --- | --- |
| 版本 | v0.1 |
| 日期 | 2026-07-22 |

---

## 前置准备

### 1. 安装 Python 3.12

机器当前为 Python 3.14.6，但 PyTorch / Transformers / flash-attn 尚无官方 3.14 wheel。

**Windows 推荐路径**：

- 从 [python.org](https://www.python.org/downloads/) 下载 Python 3.12.x 安装包（最新 3.12.x）
- 或用 pyenv-win / conda 管理多版本

### 2. 创建虚拟环境

```bash
cd e:/AMLY/works/Python/altobid

# 用 Python 3.12 创建虚拟环境
py -3.12 -m venv .venv

# 激活（Windows）
.venv\Scripts\activate

# 验证版本
python --version  # 应显示 Python 3.12.x
```

### 3. 安装 PyTorch（先于 requirements.txt）

访问 [pytorch.org](https://pytorch.org/get-started/locally/)，选择对应 CUDA 版本（RTX 4080 推荐 CUDA 12.1+）：

```bash
# 示例（CUDA 12.1）
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121
```

### 4. 安装项目依赖

```bash
pip install -r requirements.txt
```

**注意**：`requirements.txt` 中 flash-attn 已注释。Windows 安装 Flash Attention 2 需：

- 社区预编译 wheel（搜索 `flash-attn windows wheel`）
- 或本地 CUDA 工具链编译（耗时，易失败）
- **或跳过**：代码会自动回退到 `sdpa`（见架构文档 §2.2 / §5.6）

量化库（默认 NF4，`requirements.txt` 已含 `bitsandbytes`，一般无需额外操作）：

```bash
# NF4 4bit 量化（默认，运行时从 fp16 权重量化，8GB 卡推荐）
pip install bitsandbytes
```

> 为何不用 AWQ：实测 Windows + torch 2.6 下 AWQ 推理内核 `awq_ext` 加载报 ABI
> 不匹配（预编译 wheel 仅 0.0.8/0.0.9，针对旧 torch），且 autoawq 已弃用。
> bitsandbytes NF4 有官方 Windows wheel，加载官方 fp16 权重后运行时量化即可。详见架构文档 §2.2。

### 5. 下载模型权重

下载官方 **fp16** 权重（NF4 会在加载时运行时量化，无需预量化权重），约 6.8GB：

```bash
pip install huggingface_hub
huggingface-cli download Qwen/Qwen2.5-VL-3B-Instruct --local-dir ./models/Qwen2.5-VL-3B-Instruct
```

或手动从 HF 下载后放到 `models/Qwen2.5-VL-3B-Instruct/`。

---

## 开发步骤

### 阶段 1：基础设施（config / logger）

**目标**：搭建配置加载与日志框架，所有后续模块依赖此基础。

#### 1.1 创建目录结构

```bash
mkdir altobid config logs debug_frames
touch altobid/__init__.py
```

#### 1.2 编写 `config/default.yaml`

参考架构文档 §11 的配置草案，完整写入所有阈值与模型参数。

#### 1.3 编写 `altobid/config.py`

- 加载 `default.yaml` + 可选 `local.yaml` 覆盖
- 导出 `Config` 类或 dict，供全局引用

#### 1.4 编写 `altobid/__init__.py`

- 初始化 logger（`logging` 模块）
- 根据 `Config.debug.save_frames` 决定是否启用调试落盘

**验证点**：

```python
from altobid.config import Config
print(Config.model.path)  # 应输出配置的模型路径
```

---

### 阶段 2：区域框选（RegionSelector）

**目标**：用户拖拽框选屏幕矩形，返回 bbox。

#### 2.1 编写 `altobid/selector.py`

- `tkinter` 全屏 `Canvas` 覆盖层
- 鼠标按下记起点，拖拽画矩形，松开返回 `(left, top, width, height)`
- 多显示器：用 `mss.mss().monitors` 校正坐标偏移

#### 2.2 测试

```python
from altobid.selector import RegionSelector
bbox = RegionSelector().select()
print(bbox)  # (x, y, w, h)
```

拖拽后应输出正确坐标。

---

### 阶段 3：截图与变化检测（Capturer + ChangeDetector + Debouncer）

**目标**：循环抓帧，判断画面是否变化并稳定。

#### 3.1 编写 `altobid/capture.py`

- `Capturer` 类：`mss.mss().grab(bbox)`，返回 numpy BGR/BGRA 帧
- 在自己的线程内创建 mss 实例（mss 非线程安全）

#### 3.2 编写 `altobid/change_detect.py`

- `ChangeDetector`：灰度缩放 + `cv2.absdiff`，计算差异像素占比
- `Debouncer`：连续 N 帧稳定判定 + cooldown 冷却期

#### 3.3 测试

模拟采集循环，手动刷新验证码页面，观察是否正确检测到变化并稳定后放行。

```python
from altobid.capture import Capturer
from altobid.change_detect import ChangeDetector, Debouncer
# 伪代码框架
while True:
    frame = capturer.grab()
    if change_detector.changed(frame) and debouncer.stable():
        print("Trigger inference!")
```

---

### 阶段 4：预处理（Preprocessor）

**目标**：ROI 等比 resize 到 512~768，转 PIL Image。

#### 4.1 编写 `altobid/preprocess.py`

- BGR→RGB
- 等比缩放使长边落在 `min_pixels`~`max_pixels`（可先用 `cv2.resize` 预处理，或直接交给 Qwen processor）
- 转 `PIL.Image`

#### 4.2 测试

```python
from altobid.preprocess import Preprocessor
pil_img = Preprocessor().process(frame)
pil_img.show()  # 显示预处理后图像
```

---

### 阶段 5：推理引擎（InferenceEngine）

**目标**：加载 Qwen2.5-VL，输入图像 + prompt，输出答案。

#### 5.1 编写 `altobid/engine.py`

- 启动时探测 `flash_attn`，决定 `attn_implementation`
- `from_pretrained` 加载模型与 processor（仅一次，常驻显存）
- `generate()` 接口：输入 PIL Image，返回生成的文本

**关键代码框架**：

```python
try:
    import flash_attn  # noqa
    attn_impl = "flash_attention_2"
except Exception:
    attn_impl = "sdpa"

model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
    Config.model.path,
    torch_dtype=torch.float16,
    device_map="auto",
    attn_implementation=attn_impl
)
processor = AutoProcessor.from_pretrained(
    Config.model.path,
    min_pixels=Config.preprocess.min_pixels,
    max_pixels=Config.preprocess.max_pixels
)
```

#### 5.2 Prompt 构造

- System: `你是一个只解答图片中算式的助手。只输出最终数字答案，不要任何解释、单位或标点。`
- User: `计算图中的算式，直接给出答案。` + 图像

#### 5.3 测试

准备一张简单算式图，单独测试推理输出。

```python
from altobid.engine import InferenceEngine
engine = InferenceEngine()
answer_text = engine.infer(pil_image)
print(answer_text)  # 应为纯数字或简单答案
```

---

### 阶段 6：后处理与输出（PostProcessor + OutputHandler）

**目标**：从模型文本中提取答案，展示并复制到剪贴板。

#### 6.1 编写 `altobid/postprocess.py`

- 正则提取数字：`re.search(r'-?\d+', text)`
- 容错：无法解析时返回 `None` 或 "未识别"

#### 6.2 编写 `altobid/output.py`

- 控制台打印答案
- 可选：用 `pyperclip.copy(answer)` 复制到剪贴板
- 可选：简单的 tkinter 悬浮窗展示

#### 6.3 测试

```python
from altobid.postprocess import PostProcessor
from altobid.output import OutputHandler
answer = PostProcessor().parse(answer_text)
OutputHandler().show(answer)
```

---

### 阶段 7：主流程装配（main.py）

**目标**：启动采集线程 + 推理线程，用队列解耦。

#### 7.1 编写 `altobid/main.py`

- 用户框选区域（RegionSelector）
- 创建 `Queue(maxsize=1)`
- 启动**采集线程**（Capturer → ChangeDetector → Debouncer → Queue.put）
- 启动**推理线程**（Queue.get → Preprocessor → InferenceEngine → PostProcessor → OutputHandler）
- 优雅关闭（Ctrl+C 捕获、线程 join）

**伪代码框架**：

```python
def producer_thread(bbox, queue, stop_event):
    capturer = Capturer(bbox)
    detector = ChangeDetector()
    debouncer = Debouncer()
    while not stop_event.is_set():
        frame = capturer.grab()
        if detector.changed(frame) and debouncer.stable():
            try:
                queue.put(frame, block=False)  # 满则丢旧帧
            except Full:
                pass
        time.sleep(Config.capture.interval_ms / 1000)

def consumer_thread(queue, stop_event):
    engine = InferenceEngine()  # 模型常驻
    while not stop_event.is_set():
        frame = queue.get()
        pil_img = Preprocessor().process(frame)
        text = engine.infer(pil_img)
        answer = PostProcessor().parse(text)
        OutputHandler().show(answer)

if __name__ == "__main__":
    bbox = RegionSelector().select()
    queue = Queue(maxsize=1)
    stop_event = threading.Event()
    # 启动两线程...
```

#### 7.2 整合测试

运行 `python -m altobid.main`，框选验证码区域，刷新页面观察是否自动推理并输出答案。

---

### 阶段 8：调优与调试

#### 8.1 调参

根据实际表现调整 `config/local.yaml` 中的阈值：

- `change_threshold`：太敏感则误触发，太钝则漏检
- `stable_frames`：动画长则增大，否则可能抓到过渡帧
- `cooldown_s`：答案展示动画时长，防止自触发

#### 8.2 调试落盘

开启 `debug.save_frames: true`，把触发推理的帧保存到 `debug_frames/`，人工检查是否抓到了清晰完整的验证码。

#### 8.3 性能监控

可选：记录每次推理的耗时（从 Queue.get 到 OutputHandler.show），观察是否满足时延要求（目标 <1s）。

---

## 开发顺序总结

1. **配置与日志**（基础设施）
2. **区域框选**（交互入口）
3. **截图与变化检测**（采集循环核心）
4. **预处理**（图像转换）
5. **推理引擎**（模型加载与生成）
6. **后处理与输出**（答案提取与展示）
7. **主流程装配**（双线程 + 队列）
8. **调优与调试**（实战调参）

每个阶段完成后**独立测试验证**，再进入下一阶段，避免后期问题难定位。

---

## 注意事项

- **mss 线程安全**：每个使用 mss 的线程内独立创建 `mss.mss()` 实例。
- **Queue 满时丢旧帧**：`queue.put(frame, block=False)` + 捕获 `Full` 异常，或用 `queue.put_nowait()`。
- **推理线程异常处理**：模型 OOM / 解析失败不应崩溃整个程序，记日志并继续。
- **优雅关闭**：捕获 `KeyboardInterrupt`，设置 `stop_event`，等待线程 `join()`，释放模型资源。

---

> 本文档为开发指引，各阶段具体实现细节在编码中可根据实际情况调整。
