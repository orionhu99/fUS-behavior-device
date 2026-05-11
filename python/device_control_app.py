"""fUS 行为装置控制 —— 主应用。

整合：双 Nano 串口、USB 摄像头、Cue-触发式给水协议引擎、
舔水时间线可视化、事件日志 CSV 记录。
"""

import csv
import queue
import threading
import time
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

try:
    import cv2
except ImportError:
    cv2 = None

try:
    import serial
    import serial.tools.list_ports
except ImportError:
    serial = None

try:
    import winsound
except ImportError:
    winsound = None

from protocol_engine import ProtocolEngine
from config_manager import ConfigManager
from lick_plot import LickPlot
from gui_panels import (
    ConnectionPanel,
    ManualControlPanel,
    MotorControlPanel,
    ProtocolPanel,
    EventLogPanel,
)


# ═══════════════════════════════════════════════════════════
# 底层驱动类（保持与 V1 兼容）
# ═══════════════════════════════════════════════════════════

class SerialDevice:
    def __init__(self, name, event_queue):
        self.name = name
        self.event_queue = event_queue
        self.port = None
        self.thread = None
        self.running = False

    def connect(self, port_name, baud=115200):
        if serial is None:
            raise RuntimeError("pyserial 未安装")
        self.disconnect()
        self.port = serial.Serial(port_name, baudrate=baud, timeout=0.1)
        self.running = True
        self.thread = threading.Thread(target=self._reader, daemon=True)
        self.thread.start()
        self.event_queue.put(("host", self.name, "CONNECTED", port_name))

    def disconnect(self):
        self.running = False
        if self.port:
            try:
                self.port.close()
            except Exception:
                pass
        self.port = None

    def write(self, command):
        if not self.port or not self.port.is_open:
            raise RuntimeError(f"{self.name} 未连接")
        if not command.endswith("\n"):
            command += "\n"
        self.port.write(command.encode("ascii"))
        self.event_queue.put(("host", self.name, "TX", command.strip()))

    def _reader(self):
        while self.running and self.port and self.port.is_open:
            try:
                raw = self.port.readline().decode("utf-8", errors="replace").strip()
            except Exception as exc:
                self.event_queue.put(("host", self.name, "SERIAL_ERROR", str(exc)))
                break
            if raw:
                self.event_queue.put(("serial", self.name, "RX", raw))


class VideoRecorder:
    """摄像头预览与录像。

    预览模式下打开 cv2.imshow 小窗实时显示画面，不保存。
    录像模式下同时预览 + 写入 AVI + 帧时间戳 CSV。
    摄像头由预览或录像首次启动时打开，两者都停止后释放。
    """

    def __init__(self, event_queue):
        self.event_queue = event_queue
        self.previewing = False
        self.recording = False
        self.thread = None
        self.cap = None
        self.writer = None
        self.timestamp_file = None
        self.timestamp_writer = None
        self._camera_index = 0
        self._fps = 30.0

    # ── 预览 ────────────────────────────────────────

    def start_preview(self, camera_index=0):
        if cv2 is None:
            raise RuntimeError("opencv-python 未安装")
        if self.previewing:
            return
        self._camera_index = int(camera_index)
        self._ensure_camera()
        self.previewing = True
        self._start_loop_if_needed()
        self.event_queue.put(("host", "camera", "PREVIEW_START", ""))

    def stop_preview(self):
        if not self.previewing:
            return
        self.previewing = False
        self._stop_loop_if_needed()
        self.event_queue.put(("host", "camera", "PREVIEW_STOP", ""))

    @property
    def is_previewing(self):
        return self.previewing

    # ── 录像 ────────────────────────────────────────

    def start_recording(self, camera_index, output_dir, fps=30.0):
        if cv2 is None:
            raise RuntimeError("opencv-python 未安装")
        if self.recording:
            return

        self._camera_index = int(camera_index)
        self._fps = float(fps)
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        video_path = output_dir / f"behavior_{stamp}.avi"
        ts_path = output_dir / f"behavior_{stamp}_frames.csv"

        self._ensure_camera()
        width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or 640
        height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 480
        fourcc = cv2.VideoWriter_fourcc(*"MJPG")
        self.writer = cv2.VideoWriter(str(video_path), fourcc, float(fps), (width, height))

        self.timestamp_file = open(ts_path, "w", newline="", encoding="utf-8")
        self.timestamp_writer = csv.writer(self.timestamp_file)
        self.timestamp_writer.writerow(["frame", "host_time_s", "host_monotonic_s"])

        self.recording = True
        self._start_loop_if_needed()
        self.event_queue.put(("host", "camera", "RECORDING_START", str(video_path)))

    def stop_recording(self):
        if not self.recording:
            return
        self.recording = False
        if self.writer:
            self.writer.release()
            self.writer = None
        if self.timestamp_file:
            self.timestamp_file.close()
            self.timestamp_file = None
        self.timestamp_writer = None
        self._stop_loop_if_needed()
        self.event_queue.put(("host", "camera", "RECORDING_STOP", ""))

    # ── 全部停止 ────────────────────────────────────

    def stop(self):
        self.stop_recording()
        self.stop_preview()

    # ── 内部 ────────────────────────────────────────

    def _ensure_camera(self):
        if self.cap is not None:
            return
        self.cap = cv2.VideoCapture(self._camera_index, cv2.CAP_DSHOW)
        if not self.cap.isOpened():
            self.cap = None
            raise RuntimeError(f"无法打开摄像头 {self._camera_index}")

    def _start_loop_if_needed(self):
        if self.thread is not None and self.thread.is_alive():
            return
        self.thread = threading.Thread(target=self._capture_loop, daemon=True)
        self.thread.start()

    def _stop_loop_if_needed(self):
        if self.previewing or self.recording:
            return
        # 两者都停了，等待线程退出
        if self.thread:
            self.thread.join(timeout=3)
            self.thread = None
        if self.cap:
            self.cap.release()
            self.cap = None
        cv2.destroyWindow("摄像头预览")

    def _capture_loop(self):
        frame_id = 0
        while (self.previewing or self.recording) and self.cap and self.cap.isOpened():
            ok, frame = self.cap.read()
            if not ok:
                self.event_queue.put(("host", "camera", "FRAME_DROP", str(frame_id)))
                time.sleep(0.01)
                continue

            # 预览窗口
            cv2.imshow("摄像头预览", frame)
            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                # 按 Q 关闭预览（不关录像）
                self.previewing = False
                self._stop_loop_if_needed()
                break

            # 写入录像文件
            if self.recording and self.writer:
                now_wall = time.time()
                now_mono = time.perf_counter()
                self.writer.write(frame)
                if self.timestamp_writer:
                    self.timestamp_writer.writerow([frame_id, f"{now_wall:.6f}", f"{now_mono:.6f}"])
                frame_id += 1

        # 线程退出时清理
        if self.cap:
            self.cap.release()
            self.cap = None
        cv2.destroyWindow("摄像头预览")


# ═══════════════════════════════════════════════════════════
# 主应用
# ═══════════════════════════════════════════════════════════

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("fUS behavior device control")
        self.geometry("1000x750")

        # 共享队列
        self.events = queue.Queue()

        # 底层设备
        self.water = SerialDevice("water", self.events)
        self.spout_motor = SerialDevice("spout_motor", self.events)
        self.video = VideoRecorder(self.events)

        # 协议引擎
        self.protocol_engine = ProtocolEngine(self.water, self.events)
        self.config_mgr = ConfigManager()

        # 日志文件
        self.log_file = None
        self.log_writer = None

        # PC beep 开关
        self.pc_beep = tk.BooleanVar(value=False)

        # 输出目录
        self.output_dir = tk.StringVar(value=str(Path.cwd() / "recordings"))

        # 构建 UI
        self._build_ui()

        # 协议引擎试次完成回调 → 舔水图表
        self.protocol_engine.on_trial_complete = self._lick_plot.add_trial

        # 协议状态变化：保留面板回调 + 增加自动录像
        self._panel_state_cb = self.protocol_engine.on_state_changed
        self.protocol_engine.on_state_changed = self._combined_state_changed

        # 定时器
        self.after(50, self._drain_events)
        self.after(20, self._tick_protocol)

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self):
        # 连接面板
        self.conn_panel = ConnectionPanel(
            self, self.water, self.spout_motor, self.video, self.output_dir
        )
        self.conn_panel._ensure_log = self._ensure_log
        self.conn_panel.pack(fill="x", padx=10, pady=6)

        # 中间：左右分栏
        mid = ttk.Frame(self)
        mid.pack(fill="both", expand=True, padx=10, pady=4)

        left = ttk.Frame(mid)
        left.pack(side="left", fill="both", expand=True)

        right = ttk.Frame(mid)
        right.pack(side="right", fill="both", expand=True, padx=(8, 0))

        # 手动控制
        self.manual_panel = ManualControlPanel(left, self.water, self.events, self.pc_beep)
        self.manual_panel.pack(fill="x", pady=2)

        # 电机控制
        self.motor_panel = MotorControlPanel(left, self.spout_motor)
        self.motor_panel.pack(fill="x", pady=2)

        # 协议控制（右侧）
        self.protocol_panel = ProtocolPanel(right, self.protocol_engine, self.config_mgr)
        self.protocol_panel.pack(fill="x", pady=2)

        # 舔水图表
        plot_frame = ttk.LabelFrame(left, text="舔水时间线")
        plot_frame.pack(fill="both", expand=True, pady=2)
        self._lick_plot = LickPlot(plot_frame)
        self._lick_plot.widget.pack(fill="both", expand=True, padx=4, pady=4)

        # 事件日志
        self.log_panel = EventLogPanel(self)
        self.log_panel.pack(fill="both", expand=True, padx=10, pady=4)

    # ── 日志 ────────────────────────────────────────

    def _ensure_log(self):
        if self.log_writer:
            return
        out = Path(self.output_dir.get())
        out.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_file = open(out / f"device_events_{stamp}.csv", "w", newline="", encoding="utf-8")
        self.log_writer = csv.writer(self.log_file)
        self.log_writer.writerow(["host_time_s", "host_monotonic_s", "source", "device", "event", "value"])

    # ── 事件处理 ────────────────────────────────────

    def _drain_events(self):
        while True:
            try:
                source, device, event, value = self.events.get_nowait()
            except queue.Empty:
                break

            wall = time.time()
            mono = time.perf_counter()

            # 日志文件
            if self.log_writer:
                self.log_writer.writerow([f"{wall:.6f}", f"{mono:.6f}", source, device, event, value])
                self.log_file.flush()

            # GUI 日志面板
            line = f"{wall:.3f} | {device} | {event} | {value}\n"
            self.log_panel.append(line)

            # 转发给协议引擎（仅 serial 源事件）
            if source == "serial" and device == "water":
                # 解析 CSV: arduino_ms,event,value
                parts = value.split(",")
                if len(parts) >= 3:
                    self.protocol_engine.handle_serial_event("water", parts[1], ",".join(parts[2:]))

        self.after(50, self._drain_events)

    def _tick_protocol(self):
        self.protocol_engine.tick()
        self.after(20, self._tick_protocol)

    def _combined_state_changed(self, state, info):
        if self._panel_state_cb:
            self._panel_state_cb(state, info)
        self._on_protocol_state(state, info)

    def _on_protocol_state(self, state, info):
        # 协议运行时自动录像，停止时自动停止
        from protocol_engine import State
        if state == State.IDLE:
            if self.video.recording:
                self.video.stop_recording()
                self.conn_panel._btn_record.config(text="录像")
        else:
            if not self.video.recording and self.water.port:
                self._ensure_log()
                try:
                    self.video.start_recording(
                        self.conn_panel.camera_index.get(),
                        self.output_dir.get()
                    )
                    self.conn_panel._btn_record.config(text="停止录像")
                except Exception:
                    pass  # 摄像头可能未连接

    # ── 关闭 ────────────────────────────────────────

    def _on_close(self):
        self.protocol_engine.stop()
        self.video.stop()
        self.water.disconnect()
        self.spout_motor.disconnect()
        if self.log_file:
            self.log_file.close()
        self.destroy()


if __name__ == "__main__":
    App().mainloop()
