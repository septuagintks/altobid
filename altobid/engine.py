"""推理引擎：加载 Qwen2.5-VL 并推理。

支持：
- Flash Attention 2 探测回退（装不上自动降 sdpa）
- AWQ/GPTQ 量化权重（由权重目录自身的 config 决定，无需额外指定）
- CPU/GPU 自适应
- 权重/依赖缺失时降级到假推理（返回占位，便于无 GPU 环境跑通流程与测试）
"""
from __future__ import annotations

import warnings
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from . import get_logger

if TYPE_CHECKING:
    from PIL import Image

log = get_logger("engine")

DEFAULT_SYSTEM_PROMPT = (
    "你是一个只解答图片中算式的助手。只输出最终数字答案，不要任何解释、单位或标点。"
)
DEFAULT_USER_PROMPT = "计算图中的算式，直接给出答案。"

# dtype 字符串到 torch dtype 的归一化映射
_DTYPE_ALIASES = {
    "fp16": "float16",
    "float16": "float16",
    "half": "float16",
    "bf16": "bfloat16",
    "bfloat16": "bfloat16",
    "fp32": "float32",
    "float32": "float32",
}


class InferenceEngine:
    """Qwen2.5-VL 推理引擎。"""

    def __init__(
        self,
        model_path: str,
        dtype: str = "fp16",
        max_new_tokens: int = 64,
        temperature: float = 0.1,
        top_p: float = 0.8,
        min_pixels: Optional[int] = None,
        max_pixels: Optional[int] = None,
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
        user_prompt: str = DEFAULT_USER_PROMPT,
    ) -> None:
        self.model_path = Path(model_path)
        self.dtype = _DTYPE_ALIASES.get(dtype.lower(), "float16")
        self.max_new_tokens = max_new_tokens
        self.temperature = temperature
        self.top_p = top_p
        self.min_pixels = min_pixels
        self.max_pixels = max_pixels
        self.system_prompt = system_prompt
        self.user_prompt = user_prompt

        self.model = None
        self.processor = None
        self.device: Optional[str] = None

        self._load_model()

    # ---- 加载 --------------------------------------------------------------

    def _detect_attn_implementation(self) -> str:
        """探测 Flash Attention 2，装不上回退到 sdpa。"""
        try:
            import flash_attn  # noqa: F401

            log.info("检测到 flash-attn，使用 flash_attention_2")
            return "flash_attention_2"
        except ImportError:
            log.info("未检测到 flash-attn，回退到 sdpa")
            return "sdpa"

    def _resolve_model_class(self):
        """返回 Qwen2.5-VL 模型类；老版本 transformers 回退到通用类。"""
        try:
            from transformers import Qwen2_5_VLForConditionalGeneration

            return Qwen2_5_VLForConditionalGeneration
        except ImportError:
            from transformers import AutoModelForImageTextToText

            log.warning(
                "transformers 无 Qwen2_5_VL 类（版本偏旧），回退 AutoModelForImageTextToText"
            )
            return AutoModelForImageTextToText

    def _load_model(self) -> None:
        """加载模型和 processor，异常时降级到假推理。"""
        try:
            import torch
            from transformers import AutoProcessor

            if not self.model_path.exists():
                raise FileNotFoundError(
                    f"模型权重不存在: {self.model_path}\n"
                    "请先下载 Qwen2.5-VL-3B-Instruct-AWQ:\n"
                    "  huggingface-cli download Qwen/Qwen2.5-VL-3B-Instruct-AWQ "
                    "--local-dir models/Qwen2.5-VL-3B-Instruct-AWQ"
                )

            if torch.cuda.is_available():
                self.device = "cuda"
                torch_dtype = getattr(torch, self.dtype)
            else:
                log.warning("CUDA 不可用，降级到 CPU（推理会很慢）")
                self.device = "cpu"
                torch_dtype = torch.float32

            attn_impl = self._detect_attn_implementation()

            log.info(
                "加载模型: %s (device=%s, dtype=%s, attn=%s)",
                self.model_path.name,
                self.device,
                torch_dtype,
                attn_impl,
            )

            proc_kwargs: dict = {"trust_remote_code": True}
            if self.min_pixels is not None:
                proc_kwargs["min_pixels"] = self.min_pixels
            if self.max_pixels is not None:
                proc_kwargs["max_pixels"] = self.max_pixels
            self.processor = AutoProcessor.from_pretrained(
                str(self.model_path), **proc_kwargs
            )

            model_cls = self._resolve_model_class()
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore", category=FutureWarning)
                self.model = model_cls.from_pretrained(
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

    # ---- 推理 --------------------------------------------------------------

    def _build_messages(self, image: "Image.Image") -> list[dict]:
        return [
            {"role": "system", "content": self.system_prompt},
            {
                "role": "user",
                "content": [
                    {"type": "image", "image": image},
                    {"type": "text", "text": self.user_prompt},
                ],
            },
        ]

    def infer(self, image: "Image.Image") -> str:
        """推理单张图片，返回模型输出文本。"""
        if self.model is None:
            log.debug("假推理模式，返回占位答案")
            return "42"

        import torch
        from qwen_vl_utils import process_vision_info

        messages = self._build_messages(image)

        text = self.processor.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        image_inputs, video_inputs = process_vision_info(messages)

        inputs = self.processor(
            text=[text],
            images=image_inputs,
            videos=video_inputs,
            padding=True,
            return_tensors="pt",
        ).to(self.device)

        with torch.inference_mode():
            output_ids = self.model.generate(
                **inputs,
                max_new_tokens=self.max_new_tokens,
                temperature=self.temperature,
                top_p=self.top_p,
                do_sample=self.temperature > 0,
            )

        # 只解码新生成的部分
        trimmed = [
            out[len(inp):]
            for inp, out in zip(inputs.input_ids, output_ids, strict=False)
        ]
        answer = self.processor.batch_decode(
            trimmed, skip_special_tokens=True, clean_up_tokenization_spaces=False
        )[0]

        log.info("推理结果: %s", answer)
        return answer.strip()
