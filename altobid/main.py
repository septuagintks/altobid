"""主流程：生产者-消费者双线程。

线程模型：
- 采集线程（主线程）：框选 -> 循环截图 -> 变化检测 -> 防抖 -> 入队
- 推理线程（子线程）：出队 -> 预处理 -> 推理 -> 后处理 -> 输出 -> 更新基准

队列容量 1：保证推理的始终是最新变化帧，采集不阻塞。
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
from .config import load_config
from .engine import InferenceEngine
from .output import OutputHandler
from .postprocess import PostProcessor
from .preprocess import Preprocessor
from .selector import RegionSelector

if TYPE_CHECKING:
    import numpy as np

log = get_logger("main")

# 全局停止标志
_stop_event = threading.Event()


def signal_handler(signum, frame):
    """Ctrl+C 优雅退出。"""
    log.info("收到中断信号，正在停止...")
    _stop_event.set()


def capture_loop(
    bbox: dict,
    detector: ChangeDetector,
    debouncer: Debouncer,
    frame_queue: queue.Queue,
    interval: float,
) -> None:
    """采集循环（主线程）：截图 -> 变化检测 -> 防抖 -> 入队。"""
    log.info("采集线程启动，监控区域: %s", bbox)

    with Capturer() as capturer:
        while not _stop_event.is_set():
            try:
                frame = capturer.grab(bbox)

                # 变化检测
                if detector.changed(frame):
                    log.debug("检测到变化")
                    # 防抖：等待稳定
                    stable_frame = debouncer.wait_stable(
                        lambda: capturer.grab(bbox), detector
                    )
                    if stable_frame is not None and not _stop_event.is_set():
                        # 非阻塞入队（满了就丢弃旧帧）
                        try:
                            frame_queue.put_nowait(stable_frame)
                            log.debug("稳定帧已入队")
                        except queue.Full:
                            # 队列满（推理慢），丢弃旧帧，放入新帧
                            try:
                                frame_queue.get_nowait()
                            except queue.Empty:
                                pass
                            frame_queue.put_nowait(stable_frame)
                            log.debug("队列已满，替换为最新帧")

                time.sleep(interval)

            except Exception as e:
                log.error("采集循环异常: %s", e, exc_info=True)
                time.sleep(interval)

    log.info("采集线程退出")


def inference_loop(
    frame_queue: queue.Queue,
    preprocessor: Preprocessor,
    engine: InferenceEngine,
    postprocessor: PostProcessor,
    output_handler: OutputHandler,
    detector: ChangeDetector,
) -> None:
    """推理循环（子线程）：出队 -> 预处理 -> 推理 -> 后处理 -> 输出。"""
    log.info("推理线程启动")

    while not _stop_event.is_set():
        try:
            # 阻塞取帧，超时 1s 检查停止标志
            frame: np.ndarray = frame_queue.get(timeout=1.0)

            log.info("开始推理...")
            # 预处理
            image = preprocessor.process(frame)

            # 推理
            raw_answer = engine.infer(image)

            # 后处理
            answer = postprocessor.clean(raw_answer)

            # 输出
            output_handler.output(answer)

            # 更新基准帧（防止冷却期后重复推理同一验证码）
            detector.update(frame)

        except queue.Empty:
            continue
        except Exception as e:
            log.error("推理循环异常: %s", e, exc_info=True)

    log.info("推理线程退出")


def main() -> int:
    """主入口。"""
    # 设置日志
    setup_logging()

    # 加载配置
    cfg = load_config()
    log.info("配置加载完成")

    # 注册信号处理
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        # 1. 区域框选
        log.info("请框选验证码区域...")
        selector = RegionSelector()
        bbox = selector.select()
        if bbox is None:
            log.warning("未选择区域，退出")
            return 1

        log.info("已选择区域: %s", bbox)

        # 2. 初始化各模块
        log.info("初始化模块...")
        detector = ChangeDetector(
            method=cfg.change_detect.method,
            threshold=cfg.change_detect.change_threshold,
            pixel_delta=cfg.change_detect.pixel_delta,
        )
        debouncer = Debouncer(
            stable_frames=cfg.change_detect.stable_frames,
            stable_threshold=cfg.change_detect.stable_threshold,
            check_interval=cfg.change_detect.check_interval,
            cooldown=cfg.change_detect.cooldown,
        )
        preprocessor = Preprocessor(
            min_pixels=cfg.preprocess.min_pixels,
            max_pixels=cfg.preprocess.max_pixels,
        )
        engine = InferenceEngine(
            model_path=cfg.model.path,
            dtype=cfg.model.dtype,
            max_new_tokens=cfg.model.max_new_tokens,
            temperature=cfg.model.temperature,
            top_p=cfg.model.top_p,
        )
        postprocessor = PostProcessor()
        output_handler = OutputHandler(
            show_window=cfg.output.show_window,
            window_duration=cfg.output.window_duration,
        )

        # 3. 创建队列（容量 1）
        frame_queue: queue.Queue = queue.Queue(maxsize=1)

        # 4. 启动推理线程
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

        # 5. 运行采集循环（主线程）
        log.info("开始监控，按 Ctrl+C 停止")
        capture_loop(
            bbox,
            detector,
            debouncer,
            frame_queue,
            cfg.capture.interval,
        )

        # 6. 等待推理线程退出
        inference_thread.join(timeout=3.0)

        log.info("程序正常退出")
        return 0

    except KeyboardInterrupt:
        log.info("用户中断")
        return 130
    except Exception as e:
        log.error("主流程异常: %s", e, exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
