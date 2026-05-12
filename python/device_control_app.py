"""fUS behavior device control - main application."""

import queue
import threading
import time
import tkinter as tk
from tkinter import ttk

# 中文字体（tkinter 默认在 Windows 上支持中文，matplotlib 在 lick_plot 中配置）

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

# PC 3.5mm 音频播放 8kHz 纯音（不依赖 Bpod/HiFi）
def play_8khz_cue(duration_ms=80, volume=0.5):
    """通过默认音频输出设备（3.5mm/音箱）播放 8kHz 正弦波。"""
    import math
    import os
    import struct
    import tempfile
    import wave

    sample_rate = 44100
    n_samples = int(sample_rate * duration_ms / 1000)
    buf = b""
    for i in range(n_samples):
        t = i / sample_rate
        val = int(32767 * volume * math.sin(2 * math.pi * 8000 * t))
        buf += struct.pack("<h", val)

    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp.close()
    try:
        with wave.open(tmp.name, "w") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(buf)
        winsound.PlaySound(tmp.name, winsound.SND_FILENAME | winsound.SND_ASYNC)
    finally:
        # 播放是异步的，延迟后删除临时文件
        import threading
        def _cleanup():
            import time as _time
            _time.sleep(duration_ms / 1000 + 0.2)
            try:
                os.unlink(tmp.name)
            except OSError:
                pass
        threading.Thread(target=_cleanup, daemon=True).start()

from protocol_engine import ProtocolEngine
from config_manager import ConfigManager
from lick_plot import LickPlot
from gui_panels import (
    ConnectionPanel,
    ManualControlPanel,
    MotorControlPanel,
    ProtocolPanel,
    StatusPanel,
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
        cv2.destroyWindow("Camera Preview")

    def _capture_loop(self):
        frame_id = 0
        while (self.previewing or self.recording) and self.cap and self.cap.isOpened():
            ok, frame = self.cap.read()
            if not ok:
                self.event_queue.put(("host", "camera", "FRAME_DROP", str(frame_id)))
                time.sleep(0.01)
                continue

            # 预览窗口
            cv2.imshow("Camera Preview", frame)
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
        cv2.destroyWindow("Camera Preview")


# ═══════════════════════════════════════════════════════════
# 主应用
# ═══════════════════════════════════════════════════════════

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("fUS behavior device control")
        self.geometry("1040x720")
        self.minsize(860, 620)

        # 共享队列
        self.events = queue.Queue()

        # 底层设备
        self.water = SerialDevice("water", self.events)
        self.spout_motor = SerialDevice("spout_motor", self.events)
        self.video = VideoRecorder(self.events)

        # 心跳
        self._last_water_rx = time.perf_counter()
        self._reconnecting = False

        # 协议引擎
        self.protocol_engine = ProtocolEngine(self.water, self.events)
        self.config_mgr = ConfigManager()

        # 统一数据管理
        self.data_mgr = None
        self._trial_results = []

        # 构建 UI
        self._build_ui()

        # 回调：试次完成 → 图表 + 收集数据
        self.protocol_engine.on_trial_complete = self._on_trial_result
        self._panel_state_cb = self.protocol_engine.on_state_changed
        self.protocol_engine.on_state_changed = self._combined_state_changed

        # Protocol 面板 → 数据管理回调
        self.protocol_panel._on_start_callback = self._on_task_start
        self.protocol_panel._on_stop_callback = self._on_task_stop

        # 定时器
        self.after(15, self._drain_events)
        self.after(20, self._tick_protocol)
        self.after(500, self._refresh_plot)
        self.after(3000, self._heartbeat)
        # 时间线初始显示
        self.after(300, lambda: self._lick_plot.refresh())

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        main_v = ttk.PanedWindow(self, orient="vertical")
        main_v.grid(row=0, column=0, sticky="nsew", padx=6, pady=4)

        # ① 连接
        self.conn_panel = ConnectionPanel(main_v, self.water, self.spout_motor, self.video)

        # ② 水平分隔：控制+电机 | Task
        top_h = ttk.PanedWindow(main_v, orient="horizontal")
        ctrl_col = ttk.Frame(top_h)
        self.manual_panel = ManualControlPanel(ctrl_col, self.water, self.events, tk.BooleanVar(value=False))
        self.manual_panel.pack(fill="x", pady=1)
        self.motor_panel = MotorControlPanel(ctrl_col, self.spout_motor)
        self.motor_panel.pack(fill="x", pady=1)
        top_h.add(ctrl_col, weight=3)

        self.protocol_panel = ProtocolPanel(top_h, self.protocol_engine, self.config_mgr)
        top_h.add(self.protocol_panel, weight=2)

        # ③ 时间线
        plot_frame = ttk.LabelFrame(main_v, text="舔水时间线")
        plot_frame.rowconfigure(0, weight=1)
        plot_frame.columnconfigure(0, weight=1)
        self._lick_plot = LickPlot(plot_frame)
        self._lick_plot.widget.pack(fill="both", expand=True, padx=2, pady=2)

        # ④ 水平分隔：状态 | 日志
        bottom_h = ttk.PanedWindow(main_v, orient="horizontal")
        self.status_panel = StatusPanel(bottom_h)
        bottom_h.add(self.status_panel, weight=1)
        self.log_panel = EventLogPanel(bottom_h)
        bottom_h.add(self.log_panel, weight=2)

        main_v.add(self.conn_panel, weight=0)
        main_v.add(top_h, weight=0)
        main_v.add(plot_frame, weight=1)
        main_v.add(bottom_h, weight=0)

    # ── Task 生命周期 ───────────────────────────────

    def _on_task_start(self):
        """Task 开始：创建数据目录 + 开始录像"""
        from data_manager import DataManager
        self.data_mgr = DataManager()
        self.data_mgr.start_session(
            base_dir=self.protocol_panel.get_data_dir(),
            protocol_params=self.protocol_engine.params
        )
        # 显示目录
        self.protocol_panel._data_dir.set(str(self.data_mgr.session_dir))
        # 自动录像
        try:
            self.video.start_recording(
                self.conn_panel.camera_index.get(),
                str(self.data_mgr.session_dir)
            )
        except Exception:
            pass

    def _on_trial_result(self, result):
        """试次完成：更新图表 + 收集数据"""
        self._lick_plot.add_trial(result)
        self._trial_results.append(result)

    def _on_task_stop(self):
        """Task 停止：保存汇总 + 停止录像"""
        if self.data_mgr:
            self.data_mgr.end_session(trial_results=self._trial_results)
            self.data_mgr = None
        self._trial_results = []
        self.video.stop_recording()
        self._lick_plot.clear()

    # ── 事件处理 ────────────────────────────────────

    def _drain_events(self):
        while True:
            try:
                source, device, event, value = self.events.get_nowait()
            except queue.Empty:
                break

            wall = time.time()
            mono = time.perf_counter()

            # 日志文件（DataManager）
            if self.data_mgr:
                self.data_mgr.log_event(wall, mono, source, device, event, value)

            # GUI 日志面板（过滤高频 SYNC 事件）
            if event != "SYNC":
                line = f"{wall:.3f} | {device} | {event} | {value}\n"
                self.log_panel.append(line)

            # 更新状态面板
            self._update_status(source, device, event, value)

            # 转发给协议引擎（仅 serial 源事件）
            if source == "serial" and device == "water":
                parts = value.split(",")
                if len(parts) >= 3:
                    evt = parts[1].strip()
                    self.protocol_engine.handle_serial_event("water", evt, ",".join(p.strip() for p in parts[2:]))

        self.after(15, self._drain_events)

    def _tick_protocol(self):
        self.protocol_engine.tick()
        self.after(20, self._tick_protocol)

    def _refresh_plot(self):
        self._lick_plot.refresh()
        self.after(500, self._refresh_plot)

    def _heartbeat(self):
        """每 3s 检测 Water Nano 是否存活，失联则自动重连"""
        if not self.water.port or not self.water.port.is_open:
            self._reconnecting = False
            self.after(3000, self._heartbeat)
            return

        elapsed = time.perf_counter() - self._last_water_rx
        if elapsed > 8.0 and not self._reconnecting:
            # 超过 8s 没收数据 → 尝试重连
            self._reconnecting = True
            port = self.water.port.port
            self.events.put(("host", "water", "HEARTBEAT", "reconnecting"))
            try:
                self.water.disconnect()
                time.sleep(1)
                self.water.connect(port)
                self._reconnecting = False
                self._last_water_rx = time.perf_counter()
                self.events.put(("host", "water", "HEARTBEAT", "reconnected"))
            except Exception:
                self.events.put(("host", "water", "HEARTBEAT", "reconnect_failed"))
                self._reconnecting = False
        else:
            # 存活中，发 STATUS 确认
            try:
                self.water.write("STATUS")
            except Exception:
                pass

        self.after(3000, self._heartbeat)

    def _update_status(self, source, device, event, value):
        # 记录心跳时间
        if device == "water" and source == "serial":
            self._last_water_rx = time.perf_counter()

        if device == "water" and event == "CONNECTED":
            self._last_water_rx = time.perf_counter()
            self.status_panel.set_water_connected()
            if "MPR121_OK" in value:
                self.status_panel.set_mpr121(True)
        elif device == "spout_motor" and event == "CONNECTED":
            self.status_panel.set_motor_connected()
        elif device == "water" and event == "RX":
            parts = value.split(",")
            if len(parts) >= 3:
                evt = parts[1].strip()
                if evt == "LICK" or evt.startswith("WINDOW_LICK"):
                    self.status_panel.set_lick(f"T+{time.perf_counter() - (self.protocol_engine._session_mono_start or 0):.1f}s")
                elif evt == "WATER" or evt == "WINDOW_REWARD":
                    self.status_panel.set_water_ev(f"T+{time.perf_counter() - (self.protocol_engine._session_mono_start or 0):.1f}s")
                elif evt == "READY":
                    self.status_panel.set_mpr121("MPR121_OK" in value)
        elif device == "spout_motor" and event == "CONNECTED":
            self.status_panel.set_motor_connected()
        elif device == "camera" and event == "PREVIEW_START":
            self.status_panel.set_camera("● 预览中")
        elif device == "camera" and event == "RECORDING_START":
            self.status_panel.set_camera("● 录像中")
        elif device == "camera" and event in ("PREVIEW_STOP", "RECORDING_STOP", "VIDEO_STOP"):
            self.status_panel.set_camera("○ 未启动")

    def _combined_state_changed(self, state, info):
        if self._panel_state_cb:
            self._panel_state_cb(state, info)
        self._on_protocol_state(state, info)
        self.status_panel.set_state(info["state"])
        self.status_panel.set_trial(str(info["trial_num"]))
        self.status_panel.set_pump(info["state"] == "TRIAL")
        self.status_panel.set_smart_water(info.get("smart_water", "正常"))

    def _on_protocol_state(self, state, info):
        pass  # 录像由 _on_task_start/_on_task_stop 统一管理

    # ── 关闭 ────────────────────────────────────────

    def _on_close(self):
        self.protocol_engine.stop()
        self.video.stop()
        self.water.disconnect()
        self.spout_motor.disconnect()
        if self.data_mgr:
            self.data_mgr.end_session()
        self.destroy()


if __name__ == "__main__":
    App().mainloop()
