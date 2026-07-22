"""主流程：生产者-消费者双线程。

- 采集线程（主线程）：框选 -> 循环截图 -> 变化检测 -> 防抖 -> 入队
- 推理线程（子线程）：出队 -> 预处理 -> 推理 -> 后处理 -> 输出 -> 更新基准

队列容量 1：始终推理最新变化帧，采集不被推理阻塞。
"""
from __future__ import annotations

import queue
import signal
import sys
import threading
import time
from typing import TYPE_CHECKING

from . import get_logger, setup_logging
from .capture import Capturer
from .change_detect import ChangeDetector, Debouncer
from .config import Config
from .engine import InferenceEngine
from .output import OutputHandler
from .postprocess import PostProcessor
from .preprocess import Preprocessor
from .selector import BBox, RegionSelector

if TYPE_CHECKING:
    import numpy as np

log = get_logger("main")

_stop_event = threading.Event()


def _signal_handler(signum, frame) -> None:
    log.info("收到中断信号，正在停止...")
    _stop_event.set()


def capture_loop(
    bbox: BBox,
    detector: ChangeDetector,
    debouncer: Debouncer,
    frame_queue: "queue.Queue[np.ndarray]",
    interval_s: float,
) -> None:
    """采集循环：截图 -> 变化检测 -> 防抖 -> 入队。"""
    log.info("采集线程启动，监控区域: %s", bbox)
    with Capturer(bbox) as capturer:
        while not _stop_event.is_set():
            try:
                frame = capturer.grab()
                # 仅当相对基准发生变化时，才交给防抖累积稳定
                if detector.changed(frame):
                    if debouncer.push(frame):
                        _enqueue_latest(frame_queue, frame)
                        log.debug("稳定帧已入队")
                else:
                    debouncer.reset()  # 回到基准，取消未完成的稳定累积
                time.sleep(interval_s)
            except Exception as e:  # 单帧异常不应终止循环
                log.error("采集循环异常: %s", e, exc_info=True)
                time.sleep(interval_s)
    log.info("采集线程退出")


def _enqueue_latest(frame_queue: "queue.Queue[np.ndarray]", frame: "np.ndarray") -> None:
    """入队最新帧；队列满则丢弃旧帧（保证推理的是最新变化）。"""
    try:
        frame_queue.put_nowait(frame)
    except queue.Full:
        try:
            frame_queue.get_nowait()
        except queue.Empty:
            pass
        try:
            frame_queue.put_nowait(frame)
        except queue.Full:
            pass


def inference_loop(
    frame_queue: "queue.Queue[np.ndarray]",
    preprocessor: Preprocessor,
    engine: InferenceEngine,
    postprocessor: PostProcessor,
    output_handler: OutputHandler,
    detector: ChangeDetector,
) -> None:
    """推理循环：出队 -> 预处理 -> 推理 -> 后处理 -> 输出 -> 更新基准。"""
    log.info("推理线程启动")
    while not _stop_event.is_set():
        try:
            frame = frame_queue.get(timeout=1.0)
        except queue.Empty:
            continue
        try:
            image = preprocessor.process(frame)
            raw = engine.infer(image)
            answer = postprocessor.clean(raw)
            output_handler.output(answer)
            # 提交后更新基准：冷却期后同一验证码不再重复推理
            detector.update(frame)
        except Exception as e:
            log.error("推理循环异常: %s", e, exc_info=True)
    log.info("推理线程退出")


def _build_components() -> tuple:
    """按配置构建各组件。"""
    cd = Config.change_detect
    detector = ChangeDetector(
        method=cd.method,
        downscale=cd.downscale,
        pixel_delta=cd.pixel_delta,
        change_threshold=cd.change_threshold,
    )
    debouncer = Debouncer(
        stable_frames=cd.stable_frames,
        stable_threshold=cd.stable_threshold,
        cooldown_s=cd.cooldown_s,
        downscale=cd.downscale,
        pixel_delta=cd.pixel_delta,
    )
    preprocessor = Preprocessor(
        min_pixels=Config.preprocess.min_pixels,
        max_pixels=Config.preprocess.max_pixels,
    )
    m = Config.model
    engine = InferenceEngine(
        model_path=m.path,
        dtype=m.dtype,
        max_new_tokens=m.max_new_tokens,
        temperature=m.temperature,
        top_p=m.top_p,
        min_pixels=Config.preprocess.min_pixels,
        max_pixels=Config.preprocess.max_pixels,
        system_prompt=m.system_prompt,
        user_prompt=m.user_prompt,
    )
    postprocessor = PostProcessor()
    output_handler = OutputHandler(
        show_window=Config.output.show_window,
        copy_to_clipboard=Config.output.copy_to_clipboard,
        window_duration_ms=Config.output.window_duration_ms,
    )
    return detector, debouncer, preprocessor, engine, postprocessor, output_handler


def main() -> int:
    setup_logging(level=Config.logging.level, log_file=Config.logging.file)
    log.info("altobid 启动")

    signal.signal(signal.SIGINT, _signal_handler)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _signal_handler)

    # 1. 框选区域
    log.info("请框选验证码区域（Esc 取消）...")
    bbox = RegionSelector().select()
    if bbox is None:
        log.warning("未选择区域，退出")
        return 1

    # 2. 构建组件（含模型加载，耗时）
    log.info("初始化组件（加载模型可能需要数秒）...")
    (
        detector,
        debouncer,
        preprocessor,
        engine,
        postprocessor,
        output_handler,
    ) = _build_components()

    # 3. 队列 + 推理线程
    frame_queue: "queue.Queue[np.ndarray]" = queue.Queue(maxsize=1)
    inference_thread = threading.Thread(
        target=inference_loop,
        args=(
            frame_queue,
            preprocessor,
            engine,
            postprocessor,
            output_handler,
            detector,
        ),
        daemon=True,
    )
    inference_thread.start()

    # 4. 采集循环（主线程）
    interval_s = Config.capture.interval_ms / 1000.0
    log.info("开始监控，按 Ctrl+C 停止")
    try:
        capture_loop(bbox, detector, debouncer, frame_queue, interval_s)
    except KeyboardInterrupt:
        _stop_event.set()

    inference_thread.join(timeout=3.0)
    log.info("程序退出")
    return 0


if __name__ == "__main__":
    sys.exit(main())
