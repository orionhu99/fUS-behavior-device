"""嵌入式 matplotlib 舔水时间线图表。

在 tkinter 中显示：
- 上方：试次栅格图（trial × time），显示 cue、舔水、给水事件
- 下方：累积舔水直方图（按试次）
"""

from collections import deque

import matplotlib
matplotlib.use("TkAgg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure


class LickPlot:
    """舔水时间线可视化。"""

    def __init__(self, parent, max_trials_display=40):
        self._trials = deque(maxlen=max_trials_display)
        self._fig = Figure(figsize=(8, 2.5), dpi=100)
        self._fig.tight_layout(pad=2.0)

        gs = self._fig.add_gridspec(2, 1, height_ratios=[2, 1], hspace=0.35)
        self._ax_raster = self._fig.add_subplot(gs[0, 0])
        self._ax_hist = self._fig.add_subplot(gs[1, 0])

        self._ax_raster.set_ylabel("试次")
        self._ax_raster.set_xlabel("试次内时间 (s)")
        self._ax_hist.set_ylabel("累积")
        self._ax_hist.set_xlabel("试次号")

        self._canvas = FigureCanvasTkAgg(self._fig, master=parent)
        self._canvas_widget = self._canvas.get_tk_widget()

    @property
    def widget(self):
        return self._canvas_widget

    def add_trial(self, trial_result):
        """添加一个完成的试次数据。

        trial_result: TrialResult namedtuple
        """
        self._trials.append(trial_result)
        self._redraw()

    def clear(self):
        self._trials.clear()
        self._redraw()

    def _redraw(self):
        self._ax_raster.clear()
        self._ax_hist.clear()

        if not self._trials:
            self._canvas.draw()
            return

        # 构建栅格图数据
        n = len(self._trials)
        y_labels = []
        cue_times = []
        lick_times = []
        reward_times = []
        outcomes = []

        for i, t in enumerate(self._trials):
            y = n - i  # 最新试次在顶部
            y_labels.append(str(t.trial_num))
            outcomes.append(t.outcome)

            if t.cue_time is not None:
                # 计算相对时间（以 cue 为 0）
                ref = t.cue_time
                cue_times.append((y, 0.0))
                if t.lick_time is not None:
                    lick_times.append((y, t.lick_time - ref))
                if t.reward_time is not None:
                    reward_times.append((y, t.reward_time - ref))

        # 栅格图
        for y, x in cue_times:
            self._ax_raster.axvline(x=0, color="gray", alpha=0.3, linewidth=0.5)
            self._ax_raster.plot(x, y, "b|", markersize=8, label="Cue" if y == n else "")

        for y, x in lick_times:
            color = "green" if outcomes[n - y] == "REWARDED" else "orange"
            self._ax_raster.plot(x, y, "o", color=color, markersize=4, alpha=0.8)

        for y, x in reward_times:
            self._ax_raster.plot(x, y, "r*", markersize=6)

        self._ax_raster.set_yticks(range(1, n + 1))
        self._ax_raster.set_yticklabels(y_labels, fontsize=7)
        self._ax_raster.set_ylim(0.5, n + 0.5)
        self._ax_raster.axvline(x=0, color="blue", alpha=0.15, linewidth=3)

        # 累积直方图
        rewarded_count = sum(1 for t in self._trials if t.outcome == "REWARDED")
        missed_count = sum(1 for t in self._trials if t.outcome == "MISSED")

        trial_nums = [t.trial_num for t in self._trials]
        cum_rewarded = []
        cum = 0
        for t in self._trials:
            if t.outcome == "REWARDED":
                cum += 1
            cum_rewarded.append(cum)

        x_range = max(1, len(self._trials))
        self._ax_hist.plot(
            range(1, len(self._trials) + 1), cum_rewarded,
            "g-", linewidth=2, label=f"给水={rewarded_count}"
        )
        self._ax_hist.set_xlim(0.5, x_range + 0.5)
        self._ax_hist.legend(fontsize=7, loc="upper left")

        self._canvas.draw()
