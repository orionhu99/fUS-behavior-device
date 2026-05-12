"""GUI 面板：连接、手动控制、电机、协议、事件日志。"""

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

try:
    import serial.tools.list_ports
except ImportError:
    serial = None


# ═══════════════════════════════════════════════════════════
# 连接面板
# ═══════════════════════════════════════════════════════════

class ConnectionPanel(ttk.LabelFrame):
    def __init__(self, parent, water_dev, spout_dev, video):
        super().__init__(parent, text="连接", padding=6)
        self.water = water_dev
        self.spout = spout_dev
        self.video = video
        self._preview_on = False
        self._build()

    def _build(self):
        ports = self._list_ports()

        self.water_port = tk.StringVar()
        self.z_port = tk.StringVar()
        self.camera_index = tk.StringVar(value="0")

        row = 0
        ttk.Label(self, text="Water Nano").grid(row=row, column=0, sticky="w", padx=2, pady=2)
        ttk.Combobox(self, textvariable=self.water_port, values=ports, width=14).grid(row=row, column=1, padx=2)
        ttk.Button(self, text="连接", command=self._connect_water).grid(row=row, column=2, padx=2)

        ttk.Label(self, text="Motor Nano").grid(row=row, column=3, sticky="w", padx=2)
        ttk.Combobox(self, textvariable=self.z_port, values=ports, width=14).grid(row=row, column=4, padx=2)
        ttk.Button(self, text="连接", command=self._connect_z).grid(row=row, column=5, padx=2)

        row = 1
        ttk.Label(self, text="摄像头").grid(row=row, column=0, sticky="w", padx=2, pady=2)
        ttk.Entry(self, textvariable=self.camera_index, width=5).grid(row=row, column=1, sticky="w", padx=2)
        self._btn_preview = ttk.Button(self, text="预览", command=self._toggle_preview)
        self._btn_preview.grid(row=row, column=2, padx=2)

    def _list_ports(self):
        try:
            return [p.device for p in serial.tools.list_ports.comports()]
        except Exception:
            return []

    def _connect_water(self):
        self.water.connect(self.water_port.get())

    def _connect_z(self):
        self.spout.connect(self.z_port.get())

    def _toggle_preview(self):
        if self._preview_on:
            self.video.stop_preview()
            self._preview_on = False
            self._btn_preview.config(text="预览")
        else:
            try:
                self.video.start_preview(self.camera_index.get())
                self._preview_on = True
                self._btn_preview.config(text="关闭")
            except Exception as exc:
                messagebox.showerror("预览失败", str(exc))


# ═══════════════════════════════════════════════════════════
# 手动控制面板
# ═══════════════════════════════════════════════════════════

class ManualControlPanel(ttk.LabelFrame):
    def __init__(self, parent, water_dev, events_queue, pc_beep_var):
        super().__init__(parent, text="手动控制", padding=6)
        self.water = water_dev
        self.events = events_queue
        self.pc_beep = pc_beep_var
        self._build()

    def _build(self):
        self.dose_ms = tk.StringVar(value="400")
        self.ttl_ms = tk.StringVar(value="10")
        self.sync_ms = tk.StringVar(value="500")

        ttk.Label(self, text="剂量 ms").grid(row=0, column=0, padx=2, pady=2)
        ttk.Entry(self, textvariable=self.dose_ms, width=8).grid(row=0, column=1, padx=2)
        ttk.Button(self, text="设定", command=self._set_dose).grid(row=0, column=2, padx=2)
        ttk.Button(self, text="给水", command=self._give_water).grid(row=0, column=3, padx=2)
        ttk.Button(self, text="泵开", command=lambda: self._cmd("PUMP ON")).grid(row=0, column=4, padx=2)
        ttk.Button(self, text="泵关", command=lambda: self._cmd("PUMP OFF")).grid(row=0, column=5, padx=2)

        ttk.Label(self, text="TTL ms").grid(row=1, column=0, padx=2, pady=2)
        ttk.Entry(self, textvariable=self.ttl_ms, width=8).grid(row=1, column=1, padx=2)
        ttk.Button(self, text="设定", command=self._set_ttl).grid(row=1, column=2, padx=2)
        ttk.Label(self, text="同步 ms").grid(row=1, column=3, padx=2)
        ttk.Entry(self, textvariable=self.sync_ms, width=8).grid(row=1, column=4, padx=2)
        ttk.Button(self, text="设定", command=self._set_sync).grid(row=1, column=5, padx=2)

    def _cmd(self, cmd):
        try:
            self.water.write(cmd)
        except Exception as exc:
            messagebox.showerror("命令失败", str(exc))

    def _set_dose(self):
        self._cmd(f"DOSE {int(self.dose_ms.get())}")

    def _set_ttl(self):
        self._cmd(f"TTLMS {int(self.ttl_ms.get())}")

    def _set_sync(self):
        self._cmd(f"SYNCMS {int(self.sync_ms.get())}")

    def _give_water(self):
        self._cmd(f"WATER {int(self.dose_ms.get())}")
        if self.pc_beep.get():
            import threading
            threading.Thread(target=lambda: self._beep(), daemon=True).start()

    @staticmethod
    def _beep():
        try:
            import winsound
            winsound.Beep(8000, 80)
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════
# 电机控制面板
# ═══════════════════════════════════════════════════════════

class MotorControlPanel(ttk.LabelFrame):
    def __init__(self, parent, spout_dev):
        super().__init__(parent, text="电机控制", padding=6)
        self.spout = spout_dev
        self._build()

    def _build(self):
        self.small_step = tk.StringVar(value="50")
        self.large_step = tk.StringVar(value="500")
        self.speed_us = tk.StringVar(value="2000")

        self._status_label = ttk.Label(self, text="● 未连接", foreground="red")
        self._status_label.grid(row=0, column=0, columnspan=7, sticky="w", padx=2)

        ttk.Label(self, text="小步").grid(row=1, column=0, padx=2, pady=2)
        ttk.Entry(self, textvariable=self.small_step, width=7).grid(row=1, column=1, padx=2)
        ttk.Button(self, text="↑", width=2, command=lambda: self._step(self.small_step.get())).grid(row=1, column=2, padx=1)
        ttk.Button(self, text="↓", width=2, command=lambda: self._step("-" + self.small_step.get())).grid(row=1, column=3, padx=1)

        ttk.Label(self, text="大步").grid(row=2, column=0, padx=2, pady=2)
        ttk.Entry(self, textvariable=self.large_step, width=7).grid(row=2, column=1, padx=2)
        ttk.Button(self, text="↑", width=2, command=lambda: self._step(self.large_step.get())).grid(row=2, column=2, padx=1)
        ttk.Button(self, text="↓", width=2, command=lambda: self._step("-" + self.large_step.get())).grid(row=2, column=3, padx=1)

        ttk.Label(self, text="速度 μs").grid(row=1, column=4, padx=2)
        ttk.Entry(self, textvariable=self.speed_us, width=7).grid(row=1, column=5, padx=2)
        ttk.Button(self, text="设定", command=self._set_speed).grid(row=1, column=6, padx=2)
        ttk.Button(self, text="停止", command=lambda: self._cmd("STOP")).grid(row=2, column=4, padx=1)
        ttk.Button(self, text="归零", command=lambda: self._cmd("ZERO")).grid(row=2, column=5, padx=1)

        self._pos_label = ttk.Label(self, text="位置: --")
        self._pos_label.grid(row=2, column=6, padx=2)

    def _cmd(self, cmd):
        connected = self.spout.port and self.spout.port.is_open
        if not connected:
            self._status_label.config(text="● 未连接", foreground="red")
            messagebox.showwarning("电机未连接",
                "请先在连接面板选择 Motor Nano 的 COM 口，点击连接按钮")
            return
        self._status_label.config(text="● 已连接", foreground="green")
        try:
            self.spout.write(cmd)
        except Exception as exc:
            self._status_label.config(text="● 错误", foreground="orange")
            messagebox.showerror("电机命令失败", str(exc))

    def _step(self, steps):
        self._cmd(f"STEP {int(steps)}")

    def _set_speed(self):
        self._cmd(f"SPEED {int(self.speed_us.get())}")


# ═══════════════════════════════════════════════════════════
# 协议面板（简化版）
# ═══════════════════════════════════════════════════════════

def _make_tooltip(widget, text):
    """鼠标悬停显示提示窗"""
    tw = None
    def enter(e):
        nonlocal tw
        tw = tk.Toplevel(widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{e.x_root+10}+{e.y_root+10}")
        lbl = tk.Label(tw, text=text, font=("", 8), background="#FFFFCC",
                       relief="solid", borderwidth=1, padx=4, pady=2)
        lbl.pack()
    def leave(e):
        nonlocal tw
        if tw:
            tw.destroy()
            tw = None
    widget.bind("<Enter>", enter)
    widget.bind("<Leave>", leave)


class ProtocolPanel(ttk.LabelFrame):
    def __init__(self, parent, engine, config_manager):
        super().__init__(parent, text="Task 设置", padding=6)
        self.engine = engine
        self.config_mgr = config_manager
        self._data_dir = tk.StringVar(value="")
        self._on_stop_callback = None  # App 设置
        self._on_start_callback = None
        self._build()
        self._wire_engine()

    def _build(self):
        params = self.engine.params

        self.cue_dur = tk.StringVar(value=str(params["cue_duration_ms"]))
        self.window_dur = tk.StringVar(value=str(params["window_duration_ms"]))
        self.reward_dose = tk.StringVar(value=str(params["reward_dose_ms"]))
        self.iti_min = tk.StringVar(value=str(params["iti_min_s"]))
        self.iti_max = tk.StringVar(value=str(params["iti_max_s"]))
        self.max_trials = tk.StringVar(value=str(params["max_trials"]))
        self.session_timeout = tk.StringVar(value=str(params["session_timeout_s"]))
        self.config_name = tk.StringVar(value="default")

        # ── 参数（带 tooltip 问号）──
        r = 0
        def _qlbl(text, tip, row, col):
            '''标签文字一致，? 小号灰色悬停提示'''
            fr = ttk.Frame(self)
            fr.grid(row=row, column=col, sticky="w", padx=2, pady=1)
            ttk.Label(fr, text=text).pack(side="left")
            q = ttk.Label(fr, text=" ?", font=("", 7), foreground="#aaaaaa", cursor="hand2")
            q.pack(side="left")
            _make_tooltip(q, tip)

        _qlbl("Cue ms", "8kHz纯音播放时长", r, 0)
        ttk.Entry(self, textvariable=self.cue_dur, width=7).grid(row=r, column=1, padx=2)
        _qlbl("窗口 ms", "cue播放后等待舔水的时间，超时记为MISS", r, 2)
        ttk.Entry(self, textvariable=self.window_dur, width=7).grid(row=r, column=3, padx=2)
        ttk.Label(self, text="给水 ms").grid(row=r, column=4, sticky="w", padx=2)
        ttk.Entry(self, textvariable=self.reward_dose, width=7).grid(row=r, column=5, padx=2)

        r += 1
        _qlbl("ITI min s", "试次之间最短间隔", r, 0)
        ttk.Entry(self, textvariable=self.iti_min, width=7).grid(row=r, column=1, padx=2)
        _qlbl("max s", "试次之间最长间隔（随机取值）", r, 2)
        ttk.Entry(self, textvariable=self.iti_max, width=7).grid(row=r, column=3, padx=2)
        _qlbl("最大试次", "达到后自动停止（0=不限）", r, 4)
        ttk.Entry(self, textvariable=self.max_trials, width=7).grid(row=r, column=5, padx=2)

        r += 1
        _qlbl("最长时长 s", "实验超时自动停止", r, 0)
        ttk.Entry(self, textvariable=self.session_timeout, width=7).grid(row=r, column=1, padx=2)
        ttk.Button(self, text="应用", command=self._apply_params).grid(row=r, column=2, columnspan=2, padx=2, sticky="ew")

        ttk.Label(self, text="配置").grid(row=r, column=4, sticky="w", padx=2)
        ttk.Entry(self, textvariable=self.config_name, width=8).grid(row=r, column=5, padx=2)

        # 数据目录
        r += 1
        ttk.Label(self, text="数据目录:").grid(row=r, column=0, sticky="w", padx=2, pady=2)
        ttk.Label(self, textvariable=self._data_dir, font=("", 7), foreground="gray").grid(row=r, column=1, columnspan=4, sticky="w", padx=2)
        ttk.Button(self, text="浏览", command=self._choose_data_dir).grid(row=r, column=5, padx=2, sticky="w")

        # ── 控制按钮 ──
        r += 1
        btn_frame = ttk.Frame(self)
        btn_frame.grid(row=r, column=0, columnspan=6, pady=4, sticky="ew")
        btn_frame.columnconfigure(0, weight=1)
        btn_frame.columnconfigure(1, weight=1)
        btn_frame.columnconfigure(2, weight=1)
        btn_frame.columnconfigure(3, weight=1)
        btn_frame.columnconfigure(4, weight=1)

        self._btn_run = ttk.Button(btn_frame, text="▶ 运行", command=self._do_start)
        self._btn_run.grid(row=0, column=0, padx=1, sticky="ew")
        self._btn_pause = ttk.Button(btn_frame, text="⏸ 暂停", command=self.engine.pause, state="disabled")
        self._btn_pause.grid(row=0, column=1, padx=1, sticky="ew")
        self._btn_stop = ttk.Button(btn_frame, text="■ 停止", command=self._do_stop, state="disabled")
        self._btn_stop.grid(row=0, column=2, padx=1, sticky="ew")
        ttk.Button(btn_frame, text="保存配置", command=self._save_config).grid(row=0, column=3, padx=1, sticky="ew")
        ttk.Button(btn_frame, text="加载配置", command=self._load_config).grid(row=0, column=4, padx=1, sticky="ew")

        # ── 状态 ──
        r += 1
        self._state_label = ttk.Label(self, text="状态: IDLE", font=("", 9, "bold"))
        self._state_label.grid(row=r, column=0, columnspan=2, sticky="w", padx=2)

        r += 1
        self._trial_label = ttk.Label(self, text="试次: 0/0")
        self._trial_label.grid(row=r, column=0, columnspan=2, sticky="w", padx=2)
        self._lick_label = ttk.Label(self, text="舔: 0", foreground="#4CAF50")
        self._lick_label.grid(row=r, column=2, sticky="w", padx=2)
        self._reward_label = ttk.Label(self, text="给: 0", foreground="#1565C0")
        self._reward_label.grid(row=r, column=3, sticky="w", padx=2)
        self._miss_label = ttk.Label(self, text="错: 0", foreground="#F44336")
        self._miss_label.grid(row=r, column=4, columnspan=2, sticky="w", padx=2)

        r += 1
        self._iti_label = ttk.Label(self, text="")
        self._iti_label.grid(row=r, column=0, columnspan=6, sticky="w", padx=2)

    def _wire_engine(self):
        self.engine.on_state_changed = self._on_state_change

    def _do_start(self):
        if not self.engine.is_water_connected:
            messagebox.showwarning("未连接", "请先连接 Water Nano")
            return
        if self._on_start_callback:
            self._on_start_callback()
        self.engine.start()

    def _do_stop(self):
        if not messagebox.askyesno("停止实验", "停止实验？\n数据将自动保存。"):
            return
        if self._on_stop_callback:
            self._on_stop_callback()
        self.engine.stop()

    def _choose_data_dir(self):
        folder = filedialog.askdirectory(title="选择数据保存目录")
        if folder:
            self._data_dir.set(folder)

    def get_data_dir(self):
        d = self._data_dir.get().strip()
        return d if d else None

    def _on_state_change(self, state, info):
        self.after(0, lambda: self._update_state(state, info))

    def _update_state(self, state, info):
        self._state_label.config(text=f"状态: {state.value}")
        self._trial_label.config(text=f"试次: {info['trial_num']}/{info['max_trials']}")
        self._lick_label.config(text=f"舔: {info['total_licks']}")
        self._reward_label.config(text=f"给: {info['total_rewards']}")
        self._miss_label.config(text=f"错: {info['total_missed']}")

        if info.get("smart_water") == "跳过泵":
            self._state_label.config(text=f"状态: {state.value} (下次不泵水)")
        if info["remaining_s"] > 0:
            self._iti_label.config(text=f"{state.value} 剩余: {info['remaining_s']:.1f}s")
        else:
            self._iti_label.config(text="")

        running = state.value != "IDLE"
        self._btn_run.config(state="disabled" if running else "normal")
        self._btn_pause.config(state="normal" if running and state.value != "PAUSED" else "disabled")
        self._btn_stop.config(state="normal" if running else "disabled")

    def _apply_params(self):
        try:
            params = {
                "cue_duration_ms": int(self.cue_dur.get()),
                "window_duration_ms": int(self.window_dur.get()),
                "reward_dose_ms": int(self.reward_dose.get()),
                "iti_min_s": float(self.iti_min.get()),
                "iti_max_s": float(self.iti_max.get()),
                "max_trials": int(self.max_trials.get()),
                "session_timeout_s": int(self.session_timeout.get()),
            }
            self.engine.set_params(params)
        except ValueError as exc:
            messagebox.showerror("参数错误", str(exc))

    def _save_config(self):
        name = self.config_name.get().strip()
        if not name:
            messagebox.showerror("错误", "请输入配置名")
            return
        self._apply_params()
        self.config_mgr.save(name, {"protocol": self.engine.params})
        messagebox.showinfo("已保存", f"配置已保存: {name}")

    def _load_config(self):
        name = self.config_name.get().strip()
        if not name:
            messagebox.showerror("错误", "请输入配置名")
            return
        try:
            config = self.config_mgr.load(name)
            params = config.get("protocol", config)
            self.engine.set_params(params)
            self.cue_dur.set(str(params.get("cue_duration_ms", 80)))
            self.window_dur.set(str(params.get("window_duration_ms", 2000)))
            self.reward_dose.set(str(params.get("reward_dose_ms", 400)))
            self.iti_min.set(str(params.get("iti_min_s", 20)))
            self.iti_max.set(str(params.get("iti_max_s", 60)))
            self.max_trials.set(str(params.get("max_trials", 200)))
            self.session_timeout.set(str(params.get("session_timeout_s", 3600)))
            messagebox.showinfo("已加载", f"配置已加载: {name}")
        except FileNotFoundError:
            messagebox.showerror("错误", f"配置 '{name}' 不存在")
        except Exception as exc:
            messagebox.showerror("加载失败", str(exc))


# ═══════════════════════════════════════════════════════════
# 状态面板
# ═══════════════════════════════════════════════════════════

class StatusPanel(ttk.LabelFrame):
    def __init__(self, parent):
        super().__init__(parent, text="状态", padding=6)
        self._labels = {}
        self._build()

    def _build(self):
        FONT = ("", 10)
        FONT_VAL = ("", 10, "bold")

        items = [
            ("water", 3, 0, "Water Nano",  "○ 未连接"),
            ("motor", 3, 1, "Motor Nano",  "○ 未连接"),
            ("cam",   4, 0, "摄像头",       "○ 未启动"),
            ("mpr",   4, 1, "MPR121",       "--"),
            ("pump",  5, 0, "泵",           "○ 停止"),
            ("lick",  5, 1, "最后舔水",      "--"),
            ("state", 3, 2, "协议",          "IDLE"),
            ("trial", 4, 2, "试次",          "0"),
            ("smart", 5, 2, "下次补水",      "正常"),
        ]
        for key, r, c, label, default in items:
            ttk.Label(self, text=label, font=FONT).grid(row=r, column=c*2, sticky="e", padx=2, pady=3)
            val = tk.Label(self, text=default, font=FONT_VAL, fg="gray", anchor="w")
            val.grid(row=r, column=c*2+1, sticky="w", padx=2, pady=3)
            self._labels[key] = val

    def _set(self, key, text, color="gray"):
        if key in self._labels:
            self._labels[key].config(text=text, fg=color)

    def set_water_connected(self):  self._set("water", "● 已连接", "#2E7D32")
    def set_water_disconnected(self): self._set("water", "○ 未连接", "gray")
    def set_motor_connected(self):  self._set("motor", "● 已连接", "#2E7D32")
    def set_motor_disconnected(self): self._set("motor", "○ 未连接", "gray")
    def set_mpr121(self, ok):       self._set("mpr", "● 正常" if ok else "○ 未检测", "#2E7D32" if ok else "red")
    def set_pump(self, on):         self._set("pump", "● 运行" if on else "○ 停止", "#1565C0" if on else "gray")
    def set_camera(self, s):        self._set("cam", s, "#1565C0")
    def set_lick(self, tm):         self._set("lick", tm, "#4CAF50")
    def set_water_ev(self, tm):     self._set("water_ev", tm, "#1565C0")
    def set_state(self, s):         self._set("state", s, "#1565C0" if s not in ("IDLE",) else "gray")
    def set_trial(self, n):         self._set("trial", n, "black")
    def set_smart_water(self, s):   self._set("smart", s, "#E65100" if "跳过" in s else "gray")

    def update(self, key, value):   self._set(key, value)


# ═══════════════════════════════════════════════════════════
# 事件日志面板
# ═══════════════════════════════════════════════════════════

class EventLogPanel(ttk.LabelFrame):
    def __init__(self, parent):
        super().__init__(parent, text="事件日志", padding=4)
        self._build()

    def _build(self):
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        self._text = tk.Text(self, height=12, font=("Microsoft YaHei", 9), wrap="none")
        self._text.grid(row=0, column=0, sticky="nsew")

        scroll_y = ttk.Scrollbar(self, orient="vertical", command=self._text.yview)
        scroll_y.grid(row=0, column=1, sticky="ns")
        scroll_x = ttk.Scrollbar(self, orient="horizontal", command=self._text.xview)
        scroll_x.grid(row=1, column=0, sticky="ew")
        self._text.config(yscrollcommand=scroll_y.set, xscrollcommand=scroll_x.set)

    def append(self, text: str):
        self._text.insert("end", text)
        self._text.see("end")

    def clear(self):
        self._text.delete("1.0", "end")
