# altobid

油猴脚本 + 本地多模态模型的网页验证码自动答题器。

浏览器里的油猴脚本负责抓取拍牌出价弹窗（`.whSetPriceD`）中的**题干**与**题目图片**，
发送给本机的推理服务；服务用本地 Qwen2.5-VL-3B-Instruct 读图作答，脚本再把答案
自动填入出价输入框（`#bidprice`）。

- 完全本地推理，图片不出本机（仅在 `浏览器 ↔ 本机 127.0.0.1` 之间传输）
- **原生视觉理解**：直接读图答题，不依赖 OCR + 文本推理
- **题干驱动**：把页面上的题目文字作为 prompt 传给模型，无题干时按纯图题处理
- NF4 量化（bitsandbytes），仅需 ~2.5GB 显存
- 推理框架：Transformers + Flash Attention 2（缺失时回退 `sdpa`）

## 架构

```
┌─────────────────── 浏览器 ───────────────────┐        ┌──────── 本机 (127.0.0.1) ────────┐
│  油猴脚本 altobid.user.js                     │        │  推理服务 altobid/server.py       │
│                                               │        │                                  │
│  MutationObserver 监听 .whSetPriceD 出现       │        │  Flask                           │
│    ├─ 题干  .whpdtip  (display:none/noprompt  │  POST  │  /solve                          │
│    │        视为无题干)                        │ ─────▶ │   base64 → PIL                   │
│    ├─ 图片  img.pricecaptcha (src)            │  JSON  │   engine.infer(image, prompt)    │
│    │        GM_xmlhttpRequest 取 blob→base64  │        │   postprocess → answer           │
│    └─ 输入  #bidprice                          │ ◀───── │  /health                         │
│  用 native setter + input 事件回填答案         │ answer │  Qwen2.5-VL-3B (常驻显存)         │
└───────────────────────────────────────────────┘        └──────────────────────────────────┘
```

详见 [docs/architecture.md](docs/architecture.md)，实现步骤见 [docs/development.md](docs/development.md)。

## 快速开始

### 环境要求

- Python 3.10 ~ 3.12（**重要**：PyTorch/Transformers 尚不支持 3.13+）
- CUDA 12.1+（NF4 量化约 2.5GB 显存，fp16 约 6-8GB）
- 浏览器 + Tampermonkey（篡改猴）扩展

### 1. 安装推理服务

```bash
# 创建虚拟环境（推荐 Python 3.10-3.12）
python -m venv .venv
.venv/Scripts/activate         # Windows

# 安装 PyTorch（按 CUDA 版本，示例 CUDA 12.4）
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu124

# 其他依赖
pip install -r requirements.txt

# 下载模型权重（官方 fp16，NF4 在加载时运行时量化）
huggingface-cli download Qwen/Qwen2.5-VL-3B-Instruct --local-dir ./models/Qwen2.5-VL-3B-Instruct
```

### 2. 启动服务

```bash
python -m altobid.server
# 默认监听 http://127.0.0.1:8799，仅本机可访问
```

### 3. 安装油猴脚本

1. 浏览器安装 Tampermonkey 扩展
2. 新建脚本，粘贴 [userscript/altobid.user.js](userscript/altobid.user.js) 内容
3. 按目标站点修改脚本头部的 `@match` 规则
4. 保存启用

之后打开出价弹窗，脚本会自动抓题、请求服务、把答案填入 `#bidprice`。

## 配置

复制 [config.example.yaml](config.example.yaml) 为 `config/local.yaml`，只写需要覆盖的项
（完整默认值见 [config/default.yaml](config/default.yaml)）：

```yaml
server:
  host: 127.0.0.1
  port: 8799

model:
  path: ./models/Qwen2.5-VL-3B-Instruct
  dtype: fp16          # fp16 / bf16 / fp32
  quantization: nf4    # nf4 / none（fp16 直接推理）
  max_new_tokens: 64
```

## 测试

```bash
pytest tests/ -v
```

## 排障

脚本头 `const DEBUG = true;` 后，控制台会打印每一步 `[altobid]` 面包屑
（注入 → 启动监听 → 发现弹窗 → 抓题结果 → health 响应 → 取图 → 推理）。
**哪一步没打印，问题就在它前面那步。**

| 现象 | 原因 / 处理 |
| --- | --- |
| 连「脚本已注入」都没有 | `@match` 没匹配当前页，或油猴没启用脚本 |
| 有「注入」无「发现弹窗」 | 弹窗选择器在真实站点不同，或在更深的 iframe（脚本已不加 `@noframes`） |
| 「health 请求失败」 | 本地服务没起（`python -m altobid.server`），或油猴没放行到 `127.0.0.1` |
| 部分图能答、跨域图没反应 | 图床在 `*.aliyuncs.com` 等跨域，脚本头需 `@connect *`（或列出具体域名） |
| `GM_xmlhttpRequest 不可用` | `@grant` 缺失或被油猴禁用，检查权限设置 |

> 服务端请求日志（`"GET /health" / "POST /solve"`）打印在**启动服务的终端窗口**，
> 不是 `logs/altobid.log` 文件。

## 免责声明

本工具仅用于本人拥有合法授权的场景（如自动化测试、辅助学习）。
请勿用于绕过他人系统的安全机制。
