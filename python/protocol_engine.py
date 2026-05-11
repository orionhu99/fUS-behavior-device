"""试次状态机。

流程：IDLE → ITI → TRIAL(cue→舔水窗) → ITI → ...
智能补水：上次 MISS 则跳过泵（水未消耗），上次 REWARDED 则补水
"""

import enum
import random
import threading
import time
from collections import namedtuple

TrialResult = namedtuple("TrialResult", [
    "trial_num", "outcome", "iti_s",
    "cue_time", "lick_times",       # 试次内舔水时刻
    "iti_lick_times",               # ITI 期间的舔水时刻
])

DEFAULT_PARAMS = {
    "cue_duration_ms": 80,
    "window_duration_ms": 2000,
    "reward_dose_ms": 400,
    "iti_min_s": 20.0,
    "iti_max_s": 60.0,
    "max_trials": 200,
    "session_timeout_s": 3600,
}


class State(enum.Enum):
    IDLE = "IDLE"
    ITI = "ITI"
    TRIAL = "TRIAL"
    PAUSED = "PAUSED"


class ProtocolEngine:
    def __init__(self, serial_device, event_queue):
        self._dev = serial_device
        self._events = event_queue

        self.params = dict(DEFAULT_PARAMS)
        self.state = State.IDLE
        self._state_before_pause = None

        self._trial_num = 0
        self._total_licks = 0
        self._total_rewards = 0
        self._total_missed = 0

        self._trial_start_mono = 0.0
        self._deadline = 0.0
        self._iti_duration = 0.0
        self._trial_lick_times = []    # 本次 trial 所有舔水时刻
        self._iti_lick_times = []      # 当前 ITI 期间的舔水时刻
        self._prev_missed = False      # 上次 trial 是否 MISS
        self._session_mono_start = 0.0

        self.on_state_changed = None
        self.on_trial_complete = None
        self.on_params_changed = None

    # ── 公共 ──────────────────────────────────────────

    def start(self):
        if self.state != State.IDLE:
            return
        self._session_mono_start = time.perf_counter()
        self._trial_num = 0
        self._total_licks = 0
        self._total_rewards = 0
        self._total_missed = 0
        self._prev_missed = False
        self._transition(State.ITI)

    def stop(self):
        self._dev.write("STOP")
        self.state = State.IDLE
        self._state_before_pause = None
        self._deadline = 0.0
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

    def tick(self):
        if self.state in (State.IDLE, State.PAUSED):
            return
        self._check_session_timeout()
        self._check_deadline()

    def handle_serial_event(self, device: str, event: str, value: str):
        if device != "water":
            return

        if event == "LICK":
            self._total_licks += 1
            if self.state == State.TRIAL:
                self._trial_lick_times.append(time.perf_counter())
            elif self.state == State.ITI:
                self._iti_lick_times.append(time.perf_counter())

    # ── 状态转换 ──────────────────────────────────────

    def _transition(self, new_state: State):
        self.state = new_state
        self._deadline = 0.0
        if new_state == State.ITI:
            self._start_iti()
        elif new_state == State.TRIAL:
            self._start_trial()
        self._notify_state()

    def _start_iti(self):
        if self._trial_num > 0:
            licked = len(self._trial_lick_times) > 0
            outcome = "REWARDED" if licked else "MISSED"
            if outcome == "REWARDED":
                self._total_rewards += 1
                self._prev_missed = False
            else:
                self._total_missed += 1
                self._prev_missed = True

            result = TrialResult(
                trial_num=self._trial_num,
                outcome=outcome,
                iti_s=round(self._iti_duration, 2),
                cue_time=self._trial_start_mono,
                lick_times=list(self._trial_lick_times),
                iti_lick_times=list(self._iti_lick_times),
            )
            self._log("TRIAL_END", outcome)
            if self.on_trial_complete:
                self.on_trial_complete(result)

        self._trial_num += 1
        if 0 < self.params["max_trials"] < self._trial_num:
            self._log("SESSION_END", "MAX_TRIALS")
            self.stop()
            return

        self._trial_lick_times = []
        self._iti_lick_times = []
        iti_s = random.uniform(self.params["iti_min_s"], self.params["iti_max_s"])
        self._iti_duration = iti_s
        self._deadline = time.perf_counter() + iti_s
        self._log("ITI", f"{iti_s:.1f}s")

    def _start_trial(self):
        self._trial_start_mono = time.perf_counter()
        cue_ms = self.params["cue_duration_ms"]
        reward_ms = self.params["reward_dose_ms"]
        window_ms = self.params["window_duration_ms"]

        # 播放 8kHz cue（每次都播）
        threading.Thread(target=self._play_cue, args=(cue_ms,), daemon=True).start()

        # 智能补水：上次 MISS → 水嘴还有水，不泵
        if self._prev_missed:
            self._log("TRIAL_START", f"cue={cue_ms}ms,water=SKIP(prev_missed)")
        else:
            try:
                self._dev.write(f"WATER {int(reward_ms)}")
                self._log("TRIAL_START", f"cue={cue_ms}ms,water={reward_ms}ms")
            except Exception as e:
                self._log("TRIAL_ERR", f"water_cmd_failed: {e}")
                self.stop()
                return

        self._deadline = time.perf_counter() + window_ms / 1000.0

    def _play_cue(self, duration_ms):
        try:
            import winsound
            winsound.Beep(8000, int(duration_ms))
        except Exception:
            pass

    # ── 定时 ──────────────────────────────────────────

    def _check_deadline(self):
        if self._deadline == 0.0:
            return
        if time.perf_counter() < self._deadline:
            return
        if self.state == State.ITI:
            self._transition(State.TRIAL)
        elif self.state == State.TRIAL:
            if len(self._trial_lick_times) == 0:
                self._log("TRIAL_TIMEOUT", str(self._trial_num))
            self._transition(State.ITI)

    def _check_session_timeout(self):
        elapsed = time.perf_counter() - self._session_mono_start
        if elapsed >= self.params["session_timeout_s"]:
            self._log("SESSION_END", "TIMEOUT")
            self.stop()

    # ── 辅助 ──────────────────────────────────────────

    def _log(self, event: str, value: str):
        self._events.put(("host", "protocol", event, value))

    def _notify_state(self):
        if self.on_state_changed:
            self.on_state_changed(self.state, self._state_info())

    def _state_info(self) -> dict:
        remaining = max(0.0, self._deadline - time.perf_counter()) if self._deadline else 0.0
        skip_next = "跳过泵" if self._prev_missed else "正常"
        return {
            "state": self.state.value,
            "trial_num": self._trial_num,
            "max_trials": self.params["max_trials"],
            "total_licks": self._total_licks,
            "total_rewards": self._total_rewards,
            "total_missed": self._total_missed,
            "remaining_s": round(remaining, 1),
            "iti_duration_s": round(self._iti_duration, 1),
            "smart_water": skip_next,
        }
