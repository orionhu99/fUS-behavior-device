"""试次状态机：管理 cue-触发式给水协议。

协议流程：
IDLE → ITI → PRECUE → CUE → WINDOW → REWARD/POST_REWARD → ITI
任意状态 → PAUSED（暂停）/ IDLE（停止）

关键延迟路径（舔→给水）在 Water Nano 上自治执行，不经过 USB。
Python 端只负责试次调度和日志记录。
"""

import enum
import random
import time
from collections import namedtuple

TrialResult = namedtuple("TrialResult", [
    "trial_num", "outcome", "iti_s",
    "cue_time", "lick_time", "reward_time",
])


class State(enum.Enum):
    IDLE = "IDLE"
    ITI = "ITI"
    PRECUE = "PRECUE"
    CUE = "CUE"
    WINDOW = "WINDOW"
    POST_REWARD = "POST_REWARD"
    PAUSED = "PAUSED"


class Outcome(enum.Enum):
    PENDING = "PENDING"
    REWARDED = "REWARDED"
    MISSED = "MISSED"


DEFAULT_PARAMS = {
    "cue_duration_ms": 80,
    "precue_ms": 200,
    "window_duration_ms": 3000,
    "reward_dose_ms": 400,
    "post_reward_ms": 500,
    "iti_min_s": 20.0,
    "iti_max_s": 60.0,
    "max_trials": 200,
    "session_timeout_s": 3600,
}


class ProtocolEngine:
    """试次协议状态机。

    通过持有的 SerialDevice（water Nano）发送命令，
    通过回调将状态变化通知 GUI 面板。
    """

    def __init__(self, serial_device, event_queue):
        self._dev = serial_device
        self._events = event_queue

        # 参数
        self.params = dict(DEFAULT_PARAMS)

        # 状态
        self.state = State.IDLE
        self._state_before_pause: State | None = None
        self._trial_num = 0
        self._total_licks = 0
        self._total_rewards = 0
        self._total_missed = 0

        # 当前试次计时
        self._state_start: float = 0.0
        self._deadline: float = 0.0
        self._iti_duration: float = 0.0
        self._current_outcome = Outcome.PENDING
        self._trial_lick_time: float | None = None
        self._trial_reward_time: float | None = None
        self._trial_cue_time: float | None = None

        # 会话计时
        self._session_start: float | None = None

        # 协议引擎自己的事件日志（补充 serial 事件）
        self._mono_start: float | None = None

        # 回调
        self.on_state_changed = None        # fn(state: State, info: dict)
        self.on_trial_complete = None       # fn(result: TrialResult)
        self.on_params_changed = None        # fn(params: dict)

    # ── 公共方法 ────────────────────────────────────────

    def start(self):
        if self.state != State.IDLE:
            return
        self._session_start = time.time()
        self._mono_start = time.perf_counter()
        self._trial_num = 0
        self._total_licks = 0
        self._total_rewards = 0
        self._total_missed = 0
        self._transition(State.ITI)

    def stop(self):
        self._dev.write("STOP")
        self.state = State.IDLE
        self._state_before_pause = None
        self._state_start = 0
        self._notify_state()

    def pause(self):
        if self.state in (State.IDLE, State.PAUSED):
            return
        self._state_before_pause = self.state
        self._transition(State.PAUSED)

    def resume(self):
        if self.state != State.PAUSED or self._state_before_pause is None:
            return
        self._transition(self._state_before_pause)
        self._state_before_pause = None

    def set_params(self, params: dict):
        self.params.update(params)
        if self.on_params_changed:
            self.on_params_changed(self.params)

    # ── 由 GUI 定时驱动（~20ms 间隔）────────────────────

    def tick(self):
        if self.state in (State.IDLE, State.PAUSED):
            return
        self._check_session_timeout()
        self._check_deadline()

    # ── 串口事件处理 ────────────────────────────────────

    def handle_serial_event(self, device: str, event: str, value: str):
        """由 GUI 的 _drain_events 调用，处理来自 Nano 的事件。"""
        if device != "water":
            return

        if event == "LICK":
            self._total_licks += 1
            if self.state == State.WINDOW:
                self._trial_lick_time = time.perf_counter()

        elif event == "WINDOW_LICK":
            # Nano 在窗口内检测到舔水（已在 Nano 端触发奖励）
            pass

        elif event == "WINDOW_REWARD":
            self._current_outcome = Outcome.REWARDED
            self._total_rewards += 1
            self._trial_reward_time = time.perf_counter()

        elif event == "WINDOW_END":
            if value == "MISSED":
                self._current_outcome = Outcome.MISSED
                self._total_missed += 1
            # 无论 REWARDED 还是 MISSED，窗口结束 → 进入后奖励期或 ITI
            if self.state == State.WINDOW:
                if self._current_outcome == Outcome.REWARDED:
                    self._transition(State.POST_REWARD)
                else:
                    self._complete_trial()

    # ── 内部状态转换 ────────────────────────────────────

    def _transition(self, new_state: State):
        old = self.state
        self.state = new_state
        self._state_start = time.perf_counter()
        self._deadline = 0.0

        if new_state == State.ITI:
            self._start_iti()
        elif new_state == State.PRECUE:
            self._start_precue()
        elif new_state == State.CUE:
            self._start_cue()
        elif new_state == State.WINDOW:
            self._start_window()
        elif new_state == State.POST_REWARD:
            self._start_post_reward()

        self._notify_state()

    def _start_iti(self):
        if self._trial_num > 0 and self._current_outcome != Outcome.PENDING:
            self._finish_trial()

        self._trial_num += 1
        if self.params["max_trials"] > 0 and self._trial_num > self.params["max_trials"]:
            self._log("SESSION_END", "MAX_TRIALS")
            self._transition(State.IDLE)
            return

        self._current_outcome = Outcome.PENDING
        self._trial_lick_time = None
        self._trial_reward_time = None
        self._trial_cue_time = None

        iti_s = random.uniform(self.params["iti_min_s"], self.params["iti_max_s"])
        self._iti_duration = iti_s
        self._deadline = self._state_start + iti_s
        self._log("ITI_START", f"{iti_s:.1f}")

    def _start_precue(self):
        dur = self.params["precue_ms"] / 1000.0
        self._deadline = self._state_start + dur

    def _start_cue(self):
        self._dev.write("CUE")
        self._trial_cue_time = time.perf_counter()
        dur = self.params["cue_duration_ms"] / 1000.0
        self._deadline = self._state_start + dur
        self._log("CUE", str(self.params["cue_duration_ms"]))

    def _start_window(self):
        dur = self.params["window_duration_ms"]
        reward = self.params["reward_dose_ms"]
        self._dev.write(f"WINDOW {int(dur)} {int(reward)}")

    def _start_post_reward(self):
        dur = self.params["post_reward_ms"] / 1000.0
        self._deadline = self._state_start + dur

    def _check_deadline(self):
        if self._deadline == 0.0:
            return
        now = time.perf_counter()
        if now < self._deadline:
            return

        if self.state == State.ITI:
            if self.params["precue_ms"] > 0:
                self._transition(State.PRECUE)
            else:
                self._transition(State.CUE)

        elif self.state == State.PRECUE:
            self._transition(State.CUE)

        elif self.state == State.CUE:
            self._transition(State.WINDOW)

        elif self.state == State.POST_REWARD:
            self._complete_trial()
            self._transition(State.ITI)

    def _check_session_timeout(self):
        if self._session_start is None:
            return
        elapsed = time.time() - self._session_start
        if elapsed >= self.params["session_timeout_s"]:
            self._log("SESSION_END", "TIMEOUT")
            self.stop()

    def _complete_trial(self):
        self._finish_trial()

    def _finish_trial(self):
        result = TrialResult(
            trial_num=self._trial_num,
            outcome=self._current_outcome.name,
            iti_s=round(self._iti_duration, 2),
            cue_time=self._trial_cue_time,
            lick_time=self._trial_lick_time,
            reward_time=self._trial_reward_time,
        )
        self._log("TRIAL_END", f"{result.outcome}")
        if self.on_trial_complete:
            self.on_trial_complete(result)

    def _log(self, event: str, value: str):
        mono = time.perf_counter()
        self._events.put(("host", "protocol", event, value))

    def _notify_state(self):
        if self.on_state_changed:
            self.on_state_changed(self.state, self._state_info())

    def _state_info(self) -> dict:
        remaining = max(0.0, self._deadline - time.perf_counter()) if self._deadline else 0.0
        return {
            "state": self.state.value,
            "trial_num": self._trial_num,
            "max_trials": self.params["max_trials"],
            "total_licks": self._total_licks,
            "total_rewards": self._total_rewards,
            "total_missed": self._total_missed,
            "current_outcome": self._current_outcome.name,
            "remaining_s": round(remaining, 1),
            "iti_duration_s": round(self._iti_duration, 1),
        }
