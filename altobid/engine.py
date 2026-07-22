"""推理引擎：加载 Qwen2.5-VL 并推理。

支持：
- Flash Attention 2 探测回退（装不上自动降 sdpa）
- AWQ/GPTQ 量化权重
- CPU/GPU 自适应（无 CUDA 或权重缺失时降级到 CPU + 假推理）
"""
from __future__ import annotations

import warnings
from pathlib import Path
from typing import TYPE_CHECKING

from . import get_logger

if TYPE_CHECKING:
    from PIL import Image

log = get_logger("engine")

# 推理提示词：零样本、简洁输出
PROMPT = """这是一道小学数学题验证码，请仔细观察图片中的题目并计算答案。

要求：
1. 只输出最终数字答案，不要解释过程
2. 如果是选择题，输出选项字母（A/B/C/D）
3. 如果题目不清晰或无法识别，输出"无法识别"

答案："""


class InferenceEngine:
    """Qwen2.5-VL 推理引擎。"""

    def __init__(
        self,
        model_path: str,
        dtype: str = "float16",
        max_new_tokens: int = 64,
        temperature: float = 0.1,
        top_p: float = 0.8,
    ) -> None:
        self.model_path = Path(model_path)
        self.dtype = dtype
        self.max_new_tokens = max_new_tokens
        self.temperature = temperature
        self.top_p = top_p

        self.model = None
        self.processor = None
        self.device = None

        self._load_model()

    def _detect_attn_implementation(self) -> str:
        """探测 Flash Attention 2，装不上回退到 sdpa。"""
        try:
            import flash_attn  # noqa: F401

            log.info("检测到 flash-attn，使用 flash_attention_2")
            return "flash_attention_2"
        except ImportError:
            log.info("未检测到 flash-attn，回退到 sdpa")
            return "sdpa"

    def _load_model(self) -> None:
        """加载模型和 processor，异常时降级。"""
        try:
            import torch
            from transformers import Qwen2VLForConditionalGeneration, Qwen2VLProcessor

            if not torch.cuda.is_available():
                log.warning("CUDA 不可用，降级到 CPU（推理会很慢）")
                self.device = "cpu"
                torch_dtype = torch.float32
            else:
                self.device = "cuda"
                torch_dtype = torch.float16 if self.dtype == "float16" else torch.bfloat16

            if not self.model_path.exists():
                raise FileNotFoundError(
                    f"模型权重不存在: {self.model_path}\n"
                    "请先下载 Qwen2.5-VL-3B-Instruct-AWQ:\n"
                    "  huggingface-cli download Qwen/Qwen2.5-VL-3B-Instruct-AWQ "
                    "--local-dir models/Qwen2.5-VL-3B-Instruct-AWQ"
                )

            attn_impl = self._detect_attn_implementation()

            log.info(
                "加载模型: %s (device=%s, dtype=%s, attn=%s)",
                self.model_path.name,
                self.device,
                torch_dtype,
                attn_impl,
            )

            # 加载 processor（必须先加载，模型初始化可能用到其配置）
            self.processor = Qwen2VLProcessor.from_pretrained(
                str(self.model_path), trust_remote_code=True
            )

            # 加载模型
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore", category=FutureWarning)
                self.model = Qwen2VLForConditionalGeneration.from_pretrained(
                    str(self.model_path),
                    torch_dtype=torch_dtype,
                    device_map=self.device,
                    attn_implementation=attn_impl,
                    trust_remote_code=True,
                )

            self.model.eval()
            log.info("模型加载完成")

        except ImportError as e:
            log.error("依赖缺失，降级到假推理: %s", e)
            self._setup_dummy()
        except FileNotFoundError as e:
            log.error(str(e))
            self._setup_dummy()
        except Exception as e:
            log.error("模型加载失败，降级到假推理: %s", e)
            self._setup_dummy()

    def _setup_dummy(self) -> None:
        """无模型时的假推理模式（返回固定占位）。"""
        self.model = None
        self.processor = None
        self.device = "dummy"
        log.warning("推理引擎运行在假推理模式（调试/测试用）")

    def infer(self, image: Image.Image, prompt: str = PROMPT) -> str:
        """推理单张图片，返回模型输出文本。"""
        if self.model is None:
            log.debug("假推理模式，返回占位答案")
            return "42"

        from qwen_vl_utils import process_vision_info

        # 构建消息
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image", "image": image},
                    {"type": "text", "text": prompt},
                ],
            }
        ]

        # 应用聊天模板
        text = self.processor.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )

        # 处理图片
        image_inputs, _ = process_vision_info(messages)

        # Tokenize
        inputs = self.processor(
            text=[text],
            images=image_inputs,
            padding=True,
            return_tensors="pt",
        ).to(self.device)

        # 生成
        import torch

        with torch.inference_mode():
            output_ids = self.model.generate(
                **inputs,
                max_new_tokens=self.max_new_tokens,
                temperature=self.temperature,
                top_p=self.top_p,
                do_sample=self.temperature > 0,
            )

        # 解码（跳过输入 tokens）
        generated_ids = [
            oids[len(iids) :]
            for oids, iids in zip(output_ids, inputs.input_ids, strict=False)
        ]
        answer = self.processor.batch_decode(
            generated_ids, skip_special_tokens=True, clean_up_tokenization_spaces=False
        )[0]

        log.info("推理结果: %s", answer)
        return answer.strip()
