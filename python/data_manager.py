"""统一数据管理：自动创建时间戳目录，管理所有输出文件。"""

import csv
import json
import time
from datetime import datetime
from pathlib import Path


class DataManager:
    def __init__(self):
        self._session_dir = None
        self._events_file = None
        self._events_writer = None
        self._session_start = 0.0
        self._trial_results = []

    # ── 路径 ──────────────────────────────────────────

    @property
    def session_dir(self) -> Path | None:
        return self._session_dir

    @property
    def events_csv_path(self) -> Path | None:
        if self._session_dir:
            return self._session_dir / "events.csv"
        return None

    @property
    def video_path(self) -> Path | None:
        if self._session_dir:
            return self._session_dir / "video.avi"
        return None

    @property
    def frames_csv_path(self) -> Path | None:
        if self._session_dir:
            return self._session_dir / "video_frames.csv"
        return None

    @property
    def config_path(self) -> Path | None:
        if self._session_dir:
            return self._session_dir / "session.json"
        return None

    # ── 会话生命周期 ──────────────────────────────────

    def start_session(self, base_dir=None, protocol_params=None):
        """创建 data/时间戳/ 目录，初始化所有输出文件。"""
        if base_dir is None:
            base_dir = Path.cwd() / "data"
        else:
            base_dir = Path(base_dir)

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._session_dir = base_dir / stamp
        self._session_dir.mkdir(parents=True, exist_ok=True)

        self._session_start = time.time()

        # events.csv
        self._events_file = open(self.events_csv_path, "w", newline="", encoding="utf-8")
        self._events_writer = csv.writer(self._events_file)
        self._events_writer.writerow(["host_time_s", "host_monotonic_s", "source", "device", "event", "value"])

        # 只保留当前协议定义的有效参数（过滤残留旧 key）
        from protocol_engine import DEFAULT_PARAMS
        clean = {k: v for k, v in (protocol_params or {}).items() if k in DEFAULT_PARAMS}

        # session.json 初始骨架
        self._trial_results = []
        self._write_config(clean)

        return self._session_dir

    def end_session(self, trial_results=None):
        """写入最终汇总，关闭所有文件。"""
        if trial_results:
            self._trial_results = trial_results

        # 写入 session.json 汇总
        summary = {
            "session_start": datetime.fromtimestamp(self._session_start).isoformat(),
            "session_end": datetime.now().isoformat(),
            "duration_s": round(time.time() - self._session_start, 1),
            "total_trials": len(self._trial_results),
            "trials": [
                {
                    "trial": t.trial_num,
                    "outcome": t.outcome,
                    "iti_s": t.iti_s,
                    "cue_time": t.cue_time,
                    "lick_count": len(t.lick_times or []),
                    "iti_lick_count": len(getattr(t, 'iti_lick_times', []) or []),
                }
                for t in self._trial_results
            ],
        }
        self._write_config(summary, is_final=True)

        # 关闭 events.csv
        if self._events_file:
            self._events_file.close()
            self._events_file = None
            self._events_writer = None

    def log_event(self, wall, mono, source, device, event, value):
        """写入一条事件到 CSV。"""
        if self._events_writer:
            self._events_writer.writerow([f"{wall:.6f}", f"{mono:.6f}", source, device, event, value])
            self._events_file.flush()

    # ── 内部 ──────────────────────────────────────────

    def _write_config(self, data, is_final=False):
        """写入/更新 session.json。"""
        # 读取已有内容
        existing = {}
        if self.config_path and self.config_path.exists():
            try:
                existing = json.loads(self.config_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        existing.update(data)
        if self.config_path:
            self.config_path.write_text(
                json.dumps(existing, indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
