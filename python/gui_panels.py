"""GUI 面板：连接、手动控制、电机、协议、事件日志。

每个面板是一个 ttk.LabelFrame 子类，接收父级容器和共享对象（SerialDevice、ProtocolEngine 等）。"""

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

try:
    import serial.tools.list_ports
except ImportError:
    serial = None


class ConnectionPanel(ttk.LabelFrame):
    def __init__(self, parent, water_dev, spout_dev, video, output_dir_var):
        super().__init__(parent, text="连接")
        self.water = water_dev
        self.spout = spout_dev
        self.video = video
        self.output_dir = output_dir_var
        self._ensure_log = None  # 由 App 设置
        self._preview_on = False
        self._build()

    def _build(self):
        ports = self._list_ports()

        self.water_port = tk.StringVar()
        self.z_port = tk.StringVar()
        self.camera_index = tk.StringVar(value="0")

        ttk.Label(self, text="Water Nano").grid(row=0, column=0, sticky="w", padx=4, pady=4)
        ttk.Combobox(self, textvariable=self.water_port, values=ports, width=18).grid(row=0, column=1, padx=4)
        ttk.Button(self, text="连接", command=self._connect_water).grid(row=0, column=2, padx=4)

        ttk.Label(self, text="Motor Nano").grid(row=0, column=3, sticky="w", padx=4)
        ttk.Combobox(self, textvariable=self.z_port, values=ports, width=18).grid(row=0, column=4, padx=4)
        ttk.Button(self, text="连接", command=self._connect_z).grid(row=0, column=5, padx=4)

        ttk.Label(self, text="摄像头").grid(row=1, column=0, sticky="w", padx=4, pady=4)
        ttk.Entry(self, textvariable=self.camera_index, width=6).grid(row=1, column=1, sticky="w", padx=4)
        self._btn_preview = ttk.Button(self, text="预览", command=self._toggle_preview)
        self._btn_preview.grid(row=1, column=2, padx=4)
        self._btn_record = ttk.Button(self, text="录像", command=self._toggle_recording)
        self._btn_record.grid(row=1, column=3, padx=4)
        ttk.Button(self, text="保存目录", command=self._choose_folder).grid(row=1, column=4, padx=4)

    def _list_ports(self):
        try:
            return [p.device for p in serial.tools.list_ports.comports()]
        except Exception:
            return []

    def _connect_water(self):
        self.water.connect(self.water_port.get())
        if self._ensure_log:
            self._ensure_log()

    def _connect_z(self):
        self.spout.connect(self.z_port.get())
        if self._ensure_log:
            self._ensure_log()

    def _toggle_preview(self):
        if self._preview_on:
            self.video.stop_preview()
            self._preview_on = False
            self._btn_preview.config(text="预览")
        else:
            try:
                self.video.start_preview(self.camera_index.get())
                self._preview_on = True
                self._btn_preview.config(text="关闭预览")
            except Exception as exc:
                messagebox.showerror("预览失败", str(exc))

    def _toggle_recording(self):
        if self.video.recording:
            self.video.stop_recording()
            self._btn_record.config(text="录像")
        else:
            try:
                if self._ensure_log:
                    self._ensure_log()
                self.video.start_recording(self.camera_index.get(), self.output_dir.get())
                self._btn_record.config(text="停止录像")
            except Exception as exc:
                messagebox.showerror("录像失败", str(exc))

    def _choose_folder(self):
        folder = filedialog.askdirectory()
        if folder:
            self.output_dir.set(folder)

    def refresh_ports(self):
        ports = self._list_ports()
        for child in self.winfo_children():
            if isinstance(child, ttk.Combobox):
                child["values"] = ports


class ManualControlPanel(ttk.LabelFrame):
    def __init__(self, parent, water_dev, events_queue, pc_beep_var):
        super().__init__(parent, text="手动控制")
        self.water = water_dev
        self.events = events_queue
        self.pc_beep = pc_beep_var
        self._build()

    def _build(self):
        self.dose_ms = tk.StringVar(value="400")
        self.ttl_ms = tk.StringVar(value="10")
        self.sync_ms = tk.StringVar(value="1000")

        ttk.Label(self, text="剂量 ms").grid(row=0, column=0, padx=4, pady=4)
        ttk.Entry(self, textvariable=self.dose_ms, width=8).grid(row=0, column=1, padx=4)
        ttk.Button(self, text="设定", command=self._set_dose).grid(row=0, column=2, padx=4)
        ttk.Button(self, text="给水", command=self._give_water).grid(row=0, column=3, padx=4)
        ttk.Button(self, text="泵开", command=lambda: self._cmd("PUMP ON")).grid(row=0, column=4, padx=4)
        ttk.Button(self, text="泵关", command=lambda: self._cmd("PUMP OFF")).grid(row=0, column=5, padx=4)

        ttk.Label(self, text="TTL ms").grid(row=1, column=0, padx=4, pady=4)
        ttk.Entry(self, textvariable=self.ttl_ms, width=8).grid(row=1, column=1, padx=4)
        ttk.Button(self, text="设定", command=self._set_ttl).grid(row=1, column=2, padx=4)
        ttk.Label(self, text="同步 ms").grid(row=1, column=3, padx=4)
        ttk.Entry(self, textvariable=self.sync_ms, width=8).grid(row=1, column=4, padx=4)
        ttk.Button(self, text="设定", command=self._set_sync).grid(row=1, column=5, padx=4)
        ttk.Checkbutton(self, text="PC 8kHz", variable=self.pc_beep).grid(row=1, column=6, padx=4)

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
            try:
                import winsound
                import threading
                threading.Thread(target=lambda: winsound.Beep(8000, 80), daemon=True).start()
            except Exception:
                pass


class MotorControlPanel(ttk.LabelFrame):
    def __init__(self, parent, spout_dev):
        super().__init__(parent, text="电机控制")
        self.spout = spout_dev
        self.spout_connected = False
        self._build()

    def _build(self):
        self.small_step = tk.StringVar(value="50")
        self.large_step = tk.StringVar(value="500")
        self.speed_us = tk.StringVar(value="2000")

        # 连接状态指示
        self._status_label = ttk.Label(self, text="● 未连接", foreground="red")
        self._status_label.grid(row=0, column=0, columnspan=7, sticky="w", padx=4, pady=2)

        ttk.Label(self, text="小步").grid(row=1, column=0, padx=4, pady=4)
        ttk.Entry(self, textvariable=self.small_step, width=8).grid(row=1, column=1, padx=4)
        ttk.Button(self, text="↑", command=lambda: self._step(self.small_step.get())).grid(row=1, column=2, padx=2)
        ttk.Button(self, text="↓", command=lambda: self._step("-" + self.small_step.get())).grid(row=1, column=3, padx=2)

        ttk.Label(self, text="大步").grid(row=2, column=0, padx=4, pady=4)
        ttk.Entry(self, textvariable=self.large_step, width=8).grid(row=2, column=1, padx=4)
        ttk.Button(self, text="↑", command=lambda: self._step(self.large_step.get())).grid(row=2, column=2, padx=2)
        ttk.Button(self, text="↓", command=lambda: self._step("-" + self.large_step.get())).grid(row=2, column=3, padx=2)

        ttk.Label(self, text="速度 μs").grid(row=1, column=4, padx=4)
        ttk.Entry(self, textvariable=self.speed_us, width=8).grid(row=1, column=5, padx=4)
        ttk.Button(self, text="设定", command=self._set_speed).grid(row=1, column=6, padx=4)
        ttk.Button(self, text="停止", command=lambda: self._cmd("STOP")).grid(row=2, column=4, padx=2)
        ttk.Button(self, text="归零", command=lambda: self._cmd("ZERO")).grid(row=2, column=5, padx=2)

        self._pos_label = ttk.Label(self, text="位置: --")
        self._pos_label.grid(row=2, column=6, padx=4)

    def _cmd(self, cmd):
        connected = self.spout.port and self.spout.port.is_open
        if not connected:
            self._status_label.config(text="● 未连接", foreground="red")
            messagebox.showwarning("电机未连接",
                "请先在连接面板选择 Motor Nano 的 COM 口，点击 '连接' 按钮")
            return
        self._status_label.config(text="● 已连接", foreground="green")
        try:
            self.spout.write(cmd)
        except Exception as exc:
            self._status_label.config(text="● 通信错误", foreground="orange")
            messagebox.showerror("电机命令失败", str(exc))

    def _step(self, steps):
        self._cmd(f"STEP {int(steps)}")

    def _set_speed(self):
        self._cmd(f"SPEED {int(self.speed_us.get())}")


class ProtocolPanel(ttk.LabelFrame):
    def __init__(self, parent, engine, config_manager):
        super().__init__(parent, text="协议控制")
        self.engine = engine
        self.config_mgr = config_manager
        self._build()
        self._wire_engine()

    def _build(self):
        params = self.engine.params

        # ── 参数输入行 ──
        self.cue_dur = tk.StringVar(value=str(params["cue_duration_ms"]))
        self.window_dur = tk.StringVar(value=str(params["window_duration_ms"]))
        self.reward_dose = tk.StringVar(value=str(params["reward_dose_ms"]))
        self.precue = tk.StringVar(value=str(params["precue_ms"]))
        self.post_reward = tk.StringVar(value=str(params["post_reward_ms"]))
        self.iti_min = tk.StringVar(value=str(params["iti_min_s"]))
        self.iti_max = tk.StringVar(value=str(params["iti_max_s"]))
        self.max_trials = tk.StringVar(value=str(params["max_trials"]))
        self.session_timeout = tk.StringVar(value=str(params["session_timeout_s"]))
        self.config_name = tk.StringVar(value="default")

        row = 0
        ttk.Label(self, text="Cue ms").grid(row=row, column=0, sticky="w", padx=4, pady=2)
        ttk.Entry(self, textvariable=self.cue_dur, width=7).grid(row=row, column=1, padx=2)
        ttk.Label(self, text="窗口 ms").grid(row=row, column=2, sticky="w", padx=4)
        ttk.Entry(self, textvariable=self.window_dur, width=7).grid(row=row, column=3, padx=2)
        ttk.Label(self, text="给水 ms").grid(row=row, column=4, sticky="w", padx=4)
        ttk.Entry(self, textvariable=self.reward_dose, width=7).grid(row=row, column=5, padx=2)
        row += 1
        ttk.Label(self, text="前静默 ms").grid(row=row, column=0, sticky="w", padx=4, pady=2)
        ttk.Entry(self, textvariable=self.precue, width=7).grid(row=row, column=1, padx=2)
        ttk.Label(self, text="后消耗 ms").grid(row=row, column=2, sticky="w", padx=4)
        ttk.Entry(self, textvariable=self.post_reward, width=7).grid(row=row, column=3, padx=2)
        ttk.Label(self, text="最大试次").grid(row=row, column=4, sticky="w", padx=4)
        ttk.Entry(self, textvariable=self.max_trials, width=7).grid(row=row, column=5, padx=2)
        row += 1
        ttk.Label(self, text="ITI 最短 s").grid(row=row, column=0, sticky="w", padx=4, pady=2)
        ttk.Entry(self, textvariable=self.iti_min, width=7).grid(row=row, column=1, padx=2)
        ttk.Label(self, text="最长 s").grid(row=row, column=2, sticky="w", padx=4)
        ttk.Entry(self, textvariable=self.iti_max, width=7).grid(row=row, column=3, padx=2)
        ttk.Label(self, text="会话限时 s").grid(row=row, column=4, sticky="w", padx=4)
        ttk.Entry(self, textvariable=self.session_timeout, width=7).grid(row=row, column=5, padx=2)

        # ── 参数应用按钮 ──
        row += 1
        ttk.Button(self, text="应用参数", command=self._apply_params).grid(row=row, column=0, columnspan=2, padx=4, pady=4, sticky="ew")

        # ── 配置保存/加载 ──
        ttk.Label(self, text="配置名").grid(row=row, column=2, sticky="w", padx=4)
        ttk.Entry(self, textvariable=self.config_name, width=10).grid(row=row, column=3, padx=2)
        ttk.Button(self, text="保存", command=self._save_config).grid(row=row, column=4, padx=2)
        ttk.Button(self, text="加载", command=self._load_config).grid(row=row, column=5, padx=2)

        # ── 运行控制按钮 ──
        row += 1
        self._btn_run = ttk.Button(self, text="▶ 运行", command=self.engine.start)
        self._btn_run.grid(row=row, column=0, columnspan=2, padx=4, pady=4, sticky="ew")
        self._btn_pause = ttk.Button(self, text="⏸ 暂停", command=self.engine.pause, state="disabled")
        self._btn_pause.grid(row=row, column=2, columnspan=2, padx=4, pady=4, sticky="ew")
        self._btn_stop = ttk.Button(self, text="■ 停止", command=self.engine.stop, state="disabled")
        self._btn_stop.grid(row=row, column=4, columnspan=2, padx=4, pady=4, sticky="ew")

        # ── 状态展示 ──
        row += 1
        self._state_label = ttk.Label(self, text="状态: IDLE")
        self._state_label.grid(row=row, column=0, columnspan=2, sticky="w", padx=4)
        self._trial_label = ttk.Label(self, text="试次: 0 / 0")
        self._trial_label.grid(row=row, column=2, columnspan=2, sticky="w", padx=4)
        self._lick_label = ttk.Label(self, text="舔水: 0")
        self._lick_label.grid(row=row, column=4, sticky="w", padx=4)
        self._reward_label = ttk.Label(self, text="给水: 0")
        self._reward_label.grid(row=row, column=5, sticky="w", padx=4)

        row += 1
        self._iti_label = ttk.Label(self, text="")
        self._iti_label.grid(row=row, column=0, columnspan=3, sticky="w", padx=4)
        self._missed_label = ttk.Label(self, text="错过: 0")
        self._missed_label.grid(row=row, column=3, columnspan=2, sticky="w", padx=4)

    def _wire_engine(self):
        self.engine.on_state_changed = self._on_state_change

    def _on_state_change(self, state, info):
        self.after(0, lambda: self._update_state(state, info))

    def _update_state(self, state, info):
        self._state_label.config(text=f"状态: {state.value}")
        self._trial_label.config(text=f"试次: {info['trial_num']} / {info['max_trials']}")
        self._lick_label.config(text=f"舔水: {info['total_licks']}")
        self._reward_label.config(text=f"给水: {info['total_rewards']}")
        self._missed_label.config(text=f"错过: {info['total_missed']}")

        if info["remaining_s"] > 0 and state.value in ("ITI", "PRECUE", "CUE", "POST_REWARD"):
            self._iti_label.config(text=f"{state.value} 剩余: {info['remaining_s']:.1f}s")
        elif state.value == "WINDOW":
            self._iti_label.config(text=f"等待舔水... 结果: {info['current_outcome']}")
        else:
            self._iti_label.config(text="")

        # 按钮状态
        running = state.value not in ("IDLE",)
        self._btn_run.config(state="disabled" if running else "normal")
        self._btn_pause.config(state="normal" if running and state.value != "PAUSED" else "disabled")
        self._btn_stop.config(state="normal" if running else "disabled")

    def _apply_params(self):
        try:
            params = {
                "cue_duration_ms": int(self.cue_dur.get()),
                "precue_ms": int(self.precue.get()),
                "window_duration_ms": int(self.window_dur.get()),
                "reward_dose_ms": int(self.reward_dose.get()),
                "post_reward_ms": int(self.post_reward.get()),
                "iti_min_s": float(self.iti_min.get()),
                "iti_max_s": float(self.iti_max.get()),
                "max_trials": int(self.max_trials.get()),
                "session_timeout_s": int(self.session_timeout.get()),
            }
            self.engine.set_params(params)
            messagebox.showinfo("参数已应用", "协议参数已更新")
        except ValueError as exc:
            messagebox.showerror("参数错误", str(exc))

    def _save_config(self):
        name = self.config_name.get().strip()
        if not name:
            messagebox.showerror("错误", "请输入配置名")
            return
        self._apply_params()
        config = {
            "protocol": self.engine.params,
        }
        path = self.config_mgr.save(name, config)
        messagebox.showinfo("已保存", f"配置已保存到 {path}")

    def _load_config(self):
        name = self.config_name.get().strip()
        if not name:
            messagebox.showerror("错误", "请输入配置名")
            return
        try:
            config = self.config_mgr.load(name)
            params = config.get("protocol", config)
            self.engine.set_params(params)
            # 回填 GUI
            self.cue_dur.set(str(params.get("cue_duration_ms", 80)))
            self.window_dur.set(str(params.get("window_duration_ms", 3000)))
            self.reward_dose.set(str(params.get("reward_dose_ms", 400)))
            self.precue.set(str(params.get("precue_ms", 200)))
            self.post_reward.set(str(params.get("post_reward_ms", 500)))
            self.iti_min.set(str(params.get("iti_min_s", 20)))
            self.iti_max.set(str(params.get("iti_max_s", 60)))
            self.max_trials.set(str(params.get("max_trials", 200)))
            self.session_timeout.set(str(params.get("session_timeout_s", 3600)))
            messagebox.showinfo("已加载", f"配置 '{name}' 已加载")
        except FileNotFoundError:
            messagebox.showerror("错误", f"配置 '{name}' 不存在")
        except Exception as exc:
            messagebox.showerror("加载失败", str(exc))


class EventLogPanel(ttk.LabelFrame):
    def __init__(self, parent):
        super().__init__(parent, text="事件日志")
        self._build()

    def _build(self):
        self._text = tk.Text(self, height=14)
        self._text.pack(fill="both", expand=True, padx=4, pady=4)

        scroll = ttk.Scrollbar(self._text, command=self._text.yview)
        scroll.pack(side="right", fill="y")
        self._text.config(yscrollcommand=scroll.set)

    def append(self, text: str):
        self._text.insert("end", text)
        self._text.see("end")

    def clear(self):
        self._text.delete("1.0", "end")
