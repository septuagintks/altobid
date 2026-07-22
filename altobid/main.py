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
from .debug import FrameSaver
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


def _enable_dpi_awareness() -> None:
    """让进程 DPI 感知，保证 Tkinter 坐标与 mss 物理像素一致（Windows）。

    否则在缩放（如 150%）下框线窗口会相对截图区域向左上偏移。
    必须在创建任何 Tk 窗口之前调用。
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes

        # PROCESS_PER_MONITOR_DPI_AWARE = 2
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception as e:
            log.warning("设置 DPI 感知失败: %s", e)


def capture_loop(
    bbox: BBox,
    detector: ChangeDetector,
    debouncer: Debouncer,
    frame_queue: "queue.Queue[np.ndarray]",
    interval_s: float,
    stop: threading.Event,
) -> None:
    """采集循环：截图 -> 变化检测 -> 防抖 -> 入队。

    stop: 本采集会话的停止信号，区域变更时由 on_region_ready 置位以退出旧线程。
    """
    log.info("采集线程启动，监控区域: %s", bbox)
    with Capturer(bbox) as capturer:
        while not _stop_event.is_set() and not stop.is_set():
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
    frame_saver: FrameSaver,
) -> None:
    """推理循环：出队 -> 预处理 -> 推理 -> 后处理 -> 输出 -> 更新基准。"""
    log.info("推理线程启动")
    while not _stop_event.is_set():
        try:
            frame = frame_queue.get(timeout=1.0)
        except queue.Empty:
            continue
        try:
            t0 = time.perf_counter()
            image = preprocessor.process(frame)
            t1 = time.perf_counter()
            raw = engine.infer(image)
            t2 = time.perf_counter()
            answer = postprocessor.clean(raw)
            output_handler.output(answer)
            # 提交后更新基准：冷却期后同一验证码不再重复推理
            detector.update(frame)
            frame_saver.save(frame, answer)
            log.info(
                "延迟: 预处理 %.0fms + 推理 %.0fms = 总 %.0fms",
                (t1 - t0) * 1000,
                (t2 - t1) * 1000,
                (time.perf_counter() - t0) * 1000,
            )
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
        quantization=m.get("quantization", "none"),
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

    _enable_dpi_awareness()  # 必须在建任何窗口前

    signal.signal(signal.SIGINT, _signal_handler)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _signal_handler)

    # 1. 预加载组件（含模型，避免框选后等待）
    log.info("初始化组件（加载模型可能需要数秒）...")
    (
        detector,
        debouncer,
        preprocessor,
        engine,
        postprocessor,
        output_handler,
    ) = _build_components()

    frame_saver = FrameSaver(
        enabled=Config.debug.save_frames, out_dir=Config.debug.frames_dir
    )
    frame_queue: "queue.Queue[np.ndarray]" = queue.Queue(maxsize=1)

    # 2. 推理线程（先启动，等待队列有数据）
    inference_thread = threading.Thread(
        target=inference_loop,
        args=(
            frame_queue,
            preprocessor,
            engine,
            postprocessor,
            output_handler,
            detector,
            frame_saver,
        ),
        daemon=True,
    )
    inference_thread.start()

    # 3. 采集线程容器（在框选回调中启动/重启）
    capture_thread: Optional[threading.Thread] = None
    capture_stop: Optional[threading.Event] = None
    capture_lock = threading.Lock()

    def on_region_ready(bbox: BBox) -> None:
        """框选完成或框体调整回调：停掉旧采集线程，重置基准，起新线程。

        注意：本函数可能被 selector 从后台线程调用，会短暂 join 旧线程，
        故不应在 Tk 事件线程内直接调用（selector 已用独立线程包裹）。
        """
        nonlocal capture_thread, capture_stop
        with capture_lock:
            # 1) 停止旧采集线程并等待退出，避免多线程同时抓屏、踩 detector 状态
            if capture_stop is not None:
                capture_stop.set()
            if capture_thread is not None and capture_thread.is_alive():
                capture_thread.join(timeout=2.0)
                if capture_thread.is_alive():
                    log.warning("旧采集线程未在 2s 内退出，继续启动新线程")

            # 2) 区域已变，重置变化检测基准与防抖，新区域从干净状态开始
            detector.reset()
            debouncer.reset()

            # 3) 启动新采集线程
            capture_stop = threading.Event()
            interval_s = Config.capture.interval_ms / 1000.0
            capture_thread = threading.Thread(
                target=capture_loop,
                args=(bbox, detector, debouncer, frame_queue, interval_s, capture_stop),
                daemon=True,
            )
            capture_thread.start()
            log.info("采集线程已启动，监控区域: %s", bbox)

    # 4. 启动常驻选区窗口 + 全局热键（阻塞主线程）
    log.info("按 Ctrl+F1 触发框选，按住 Ctrl 可调整框体")
    try:
        RegionSelector(hotkey="<ctrl>+<f1>").start(on_region_ready=on_region_ready)
    except KeyboardInterrupt:
        _stop_event.set()

    inference_thread.join(timeout=3.0)
    log.info("程序退出")
    return 0


if __name__ == "__main__":
    sys.exit(main())
