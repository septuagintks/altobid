# altobid 开发步骤文档

| 项目 | altobid |
| --- | --- |
| 版本 | v0.2（油猴脚本 + 本地服务） |
| 日期 | 2026-07-23 |

本文档描述从 v0.1（屏幕采集）到 v0.2（油猴脚本 + 本地推理服务）的重构实现步骤。

---

## 前置准备

### 1. Python 3.10~3.12 虚拟环境

```bash
cd e:/AMLY/works/Python/altobid
py -3.12 -m venv .venv
.venv\Scripts\activate
python --version   # 3.12.x
```

### 2. 安装 PyTorch（先于 requirements.txt）

```bash
# 示例 CUDA 12.4
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu124
```

### 3. 安装依赖与模型

```bash
pip install -r requirements.txt
huggingface-cli download Qwen/Qwen2.5-VL-3B-Instruct --local-dir ./models/Qwen2.5-VL-3B-Instruct
```

---

## 重构步骤

### 阶段 0：清理旧链路

删除屏幕采集相关模块与依赖：

- 删 `altobid/selector.py` `capture.py` `change_detect.py` `output.py` `debug.py` `main.py`
- 删对应测试 `tests/test_selector.py` 等
- `requirements.txt` 移除 `mss` `opencv-python` `pynput`；新增 `flask`
- `config/default.yaml` 移除 `capture` / `change_detect` / `output` / `debug` 段

> `engine.py` `postprocess.py` `preprocess.py` `config.py` `__init__.py` 保留。

**验证点**：`python -c "from altobid.engine import InferenceEngine"` 不报缺模块。

---

### 阶段 1：引擎支持题干 prompt

**目标**：`InferenceEngine.infer` 接受可选的 per-request prompt。

- `infer(self, image, prompt: str | None = None)`
- 构造 messages 时，`prompt` 非空则用它做 user prompt，否则用 `self.user_prompt`。
- system prompt 保持「只输出答案」约束不变。

**验证点**：

```python
engine.infer(img)                       # 用默认 prompt
engine.infer(img, "请输入四位图形校验码")  # 用题干
```

---

### 阶段 2：预处理适配 PIL 输入

**目标**：`Preprocessor` 输入从 numpy BGR 帧改为 `PIL.Image`。

- 新增 `process_pil(image: PIL.Image) -> PIL.Image`（或让 `process` 接受 PIL）。
- 超大图按 `smart_resize` 预缩放；一般情况直接交给 Qwen processor 的 min/max_pixels。

**验证点**：喂一张本地样例 PNG，输出尺寸对齐 factor 且落在像素区间。

---

### 阶段 3：Flask 推理服务 `altobid/server.py`

**目标**：本机 HTTP 接口，接收「题干 + base64 图片」返回答案。

```python
from flask import Flask, request, jsonify
import base64, io, time
from PIL import Image
from .config import Config
from .engine import InferenceEngine
from .postprocess import PostProcessor

app = Flask(__name__)
engine = InferenceEngine(...)      # 启动时加载，常驻
post = PostProcessor()

@app.post("/solve")
def solve():
    data = request.get_json(force=True)
    img_b64 = data["image"].split(",")[-1]      # 容忍 dataURL 前缀
    image = Image.open(io.BytesIO(base64.b64decode(img_b64))).convert("RGB")
    prompt = (data.get("prompt") or "").strip() or None
    t0 = time.perf_counter()
    raw = engine.infer(image, prompt)
    answer = post.clean(raw)
    return jsonify(answer=answer, raw=raw,
                   latency_ms=round((time.perf_counter()-t0)*1000))

@app.get("/health")
def health():
    return jsonify(ready=engine.model is not None or engine.device == "dummy")

def main():
    app.run(host=Config.server.host, port=Config.server.port, threaded=True)
```

- 入口：`python -m altobid.server`。
- **仅绑定 127.0.0.1**，不加 `0.0.0.0`。
- 单请求串行推理即可（`threaded=True` 但模型本身不并发）。

**验证点**：

```bash
curl -X POST http://127.0.0.1:8799/solve \
  -H "Content-Type: application/json" \
  -d '{"image":"<base64>","prompt":"计算图中算式"}'
# -> {"answer":"...", "raw":"...", "latency_ms":...}
```

---

### 阶段 4：油猴脚本 `userscript/altobid.user.js`

**目标**：监听弹窗、抓题、请求服务、回填输入框。目标站点与
[HTMLs/](../HTMLs/) 三份样本结构类似但**或有细微差异**，抓取必须容错。

#### 4.0 样本差异与适配策略

对比 `box-1` / `box-3` / `site1` 三份样本，同类元素的写法并不一致：

| 维度 | box-1（纯图算式） | box-3（图形校验码） | site1（彩色数字） | 适配做法 |
| --- | --- | --- | --- | --- |
| 题干节点 | `display:none` + `<span>noprompt</span>` | 可见 `<span>请输入四位图形校验码</span>` | 可见**纯文本节点**（无 span）+ 内联 `font-size` | 取 `.whpdtip` 的 `textContent().trim()`，不假设有 `<span>` |
| 题干含义 | 隐藏/`noprompt` → 无题干 | 有题干 | 有题干 | 隐藏或文本 `=== 'noprompt'` 视为空 prompt |
| 图片容器 | `whpdCapItem whpdCapItem-captcha-box` | `whpdCapItem whpdCapLeft` | `whpdCapItem1 whpdCapItem-captcha-box` | **不依赖容器 class**，直接 `img.pricecaptcha` |
| 图片 src | 绝对 OSS URL | 相对路径 `inputvercode/demo009.png` | URL-encoded 绝对 URL | 用 `img.src`（浏览器已解析为绝对 URL） |
| 输入容器 | `whpdCapItem-noprompt` | `whpdCapRight` | `whpdCapItem-noprompt` | **不依赖容器 class**，直接 `#bidprice` |
| 按钮区 | `whpdBtnbox` | `whpdBtnbox` | `whpdBtnbox1` + 内联 `onclick` | 不涉及（只回填不提交） |

**原则**：只依赖三个稳定锚点 —— `.whSetPriceD`（弹窗根）、`img.pricecaptcha`（图）、
`#bidprice`（输入框），外加 `.whpdtip`（题干，可缺失）。容器 class、按钮、`alt`、
`autocomplete` 等一律不作为定位依据，以吸收目标站的差异。

- **题干取 `textContent` 而非 `innerText`**：`site1` 的文字是裸文本节点，且要能读到隐藏元素
  （`display:none` 时 `innerText` 为空，`textContent` 仍有值），据此判断是否 `noprompt`。
- **src 用 `img.src` 属性**：DOM 属性读出来是浏览器解析后的绝对 URL，`box-3` 的相对路径
  也会补全为完整地址，`GM_xmlhttpRequest` 才能取到。
- **等图片加载完成**：弹窗可能先插入、图片后到；若 `img.complete && img.naturalWidth>0`
  直接抓，否则挂 `img.addEventListener('load', ...)` 再抓。

#### 4.1 关键片段

```js
// ==UserScript==
// @name         altobid
// @match        https://目标站点/*        // 按实际站点修改
// @grant        GM_xmlhttpRequest
// @connect      127.0.0.1
// ==/UserScript==

const ENDPOINT = 'http://127.0.0.1:8799/solve';

// 1. 监听弹窗出现
new MutationObserver(() => {
  const box = document.querySelector('.whSetPriceD');
  if (box && !box.dataset.altobidDone) { box.dataset.altobidDone = '1'; handle(box); }
}).observe(document.body, { childList: true, subtree: true });

// 2. 抓题（只依赖稳定锚点，容器 class 差异一律忽略）
function extract(box) {
  const tip = box.querySelector('.whpdtip');
  // 用 textContent：site1 是裸文本节点，且隐藏元素 innerText 会为空
  const text = tip ? tip.textContent.trim() : '';
  const hidden = tip && getComputedStyle(tip).display === 'none';
  const prompt = (hidden || text === 'noprompt') ? '' : text;
  const img = box.querySelector('img.pricecaptcha');   // 不看容器 class
  const input = box.querySelector('#bidprice');
  return { prompt, img, input };
}

// 图片可能异步加载，等就绪再返回其 src（已是绝对 URL）
function waitImage(img) {
  if (img.complete && img.naturalWidth > 0) return Promise.resolve(img.src);
  return new Promise((res, rej) => {
    img.addEventListener('load', () => res(img.src), { once: true });
    img.addEventListener('error', rej, { once: true });
  });
}

// 3. 取图 -> base64（GM_xmlhttpRequest 绕过 CORS）
function fetchImage(src) {
  return new Promise((res, rej) => GM_xmlhttpRequest({
    method: 'GET', url: src, responseType: 'blob',
    onload: r => { const fr = new FileReader();
      fr.onloadend = () => res(fr.result); fr.readAsDataURL(r.response); },
    onerror: rej,
  }));
}

// 4. 请求服务
function solve(image, prompt) {
  return new Promise((res, rej) => GM_xmlhttpRequest({
    method: 'POST', url: ENDPOINT,
    headers: { 'Content-Type': 'application/json' },
    data: JSON.stringify({ image, prompt }),
    onload: r => res(JSON.parse(r.responseText).answer),
    onerror: rej,
  }));
}

// 5. React 受控输入回填
function fill(input, value) {
  const setter = Object.getOwnPropertyDescriptor(
    window.HTMLInputElement.prototype, 'value').set;
  setter.call(input, value);
  input.dispatchEvent(new Event('input', { bubbles: true }));
}

async function handle(box) {
  const { prompt, img, input } = extract(box);
  if (!img || !input) return;
  try {
    const src = await waitImage(img);     // 等图加载完成
    const image = await fetchImage(src);
    const answer = await solve(image, prompt);
    fill(input, answer);
  } catch (e) { console.error('[altobid]', e); box.dataset.altobidDone = ''; }
}
```

**注意**：

- `@match` 用占位即可，安装时按真实目标站点填写；样本页面标题为「小马哥模拟拍牌系统」。
- 只依赖 `.whSetPriceD` / `.whpdtip` / `img.pricecaptcha` / `#bidprice` 四个锚点，
  容器 class、按钮、`alt`/`autocomplete` 差异一律不影响抓取（见 §4.0）。
- 图片异步加载由 `waitImage` 处理；`src` 用 DOM 属性读出的绝对 URL，兼容相对路径样本。
- 失败时清掉 `dataset.altobidDone` 以便下次弹窗重试。

**验证点**：打开出价弹窗 → 控制台无报错 → `#bidprice` 自动出现答案。

---

### 阶段 5：联调与调优

- **服务未就绪**：脚本先 `GET /health`，`ready` 为真再抓题。
- **答案格式**：观察 `raw` 与 `answer`，按题型调 `postprocess.py` 提取规则
  （多位数字串、字母组合等）。
- **prompt 效果**：对比「带题干」与「不带题干」的正确率，必要时调 system prompt。
- **时延**：看 `latency_ms`，目标亚秒级；过慢则确认 NF4 生效、调低 max_pixels。

---

## 开发顺序总结

1. 清理旧屏幕采集链路（删模块 + 改依赖/配置）
2. 引擎支持题干 prompt
3. 预处理适配 PIL 输入
4. Flask 推理服务
5. 油猴脚本（抓题 + 取图 + 请求 + 回填）
6. 联调与调优

---

## 注意事项

- **服务仅本机**：`host` 固定 `127.0.0.1`，无鉴权，切勿对外暴露。
- **跨域取图**：油猴脚本用 `GM_xmlhttpRequest` + `@connect`，页面 `fetch` 会被 CORS 拦。
- **React 回填**：必须原生 setter + `input` 事件，直接 `.value=` 不触发状态更新。
- **推理异常不崩服务**：捕获并返回 JSON 错误，脚本侧不回填。
- **弹窗去重**：用 `dataset` 标记，避免 MutationObserver 重复触发同一弹窗。

---

> 本文档为 v0.2 重构指引，各阶段具体实现细节在编码中可根据实际情况调整。
