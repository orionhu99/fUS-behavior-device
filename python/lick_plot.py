"""嵌入式 matplotlib 舔水时间线图表。

在 tkinter 中显示试次栅格图（trial × time），cue/舔/给水事件。
"""

from collections import deque

import matplotlib
matplotlib.use("TkAgg")
import matplotlib.font_manager as fm
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

# 中文字体
_SYS_FONT = None
for name in ["Microsoft YaHei", "SimHei", "WenQuanYi Micro Hei", "Noto Sans CJK SC"]:
    for f in fm.fontManager.ttflist:
        if f.name == name:
            _SYS_FONT = f.name
            break
    if _SYS_FONT:
        break
if _SYS_FONT:
    matplotlib.rcParams["font.family"] = _SYS_FONT
matplotlib.rcParams["axes.unicode_minus"] = False


class LickPlot:
    """舔水时间线可视化——每个试次一行，实时更新。"""

    def __init__(self, parent, max_trials=60):
        self._trials = deque(maxlen=max_trials)
        self._fig = Figure(figsize=(7, 2.2), dpi=96)
        self._fig.set_tight_layout(True)

        self._ax = self._fig.add_subplot(111)
        self._ax.set_xlabel("以 cue 为 0 的时间 (s)")
        self._ax.set_ylabel("试次")

        self._canvas = FigureCanvasTkAgg(self._fig, master=parent)
        self._canvas_widget = self._canvas.get_tk_widget()

    @property
    def widget(self):
        return self._canvas_widget

    def add_trial(self, result):
        self._trials.append(result)
        self._redraw()

    def clear(self):
        self._trials.clear()
        self._redraw()

    def _redraw(self):
        self._ax.clear()
        if not self._trials:
            self._canvas.draw()
            return

        n = len(self._trials)
        offset = max(t.lick_time - t.cue_time if (t.cue_time and t.lick_time) else 5.0
                     for t in self._trials)
        xlim = (-1.0, offset + 2.0)
        self._ax.set_xlim(*xlim)
        self._ax.set_ylim(0.3, n + 0.7)

        y_labels = []
        min_t = None

        for i, t in enumerate(self._trials):
            y = n - i
            y_labels.append(str(t.trial_num))
            ref = t.cue_time

            if ref is not None:
                if min_t is None:
                    min_t = ref
                # cue 线
                self._ax.axhline(y=y, color="#e0e0e0", linewidth=0.5, zorder=0)
                # lick 点
                if t.lick_time is not None:
                    offset_s = t.lick_time - ref
                    c = "#2ecc71" if t.outcome == "REWARDED" else "#e67e22"
                    self._ax.plot(offset_s, y, "o", color=c, markersize=5, zorder=3)
                # reward 点
                if t.reward_time is not None:
                    offset_s = t.reward_time - ref
                    self._ax.plot(offset_s, y, "D", color="#e74c3c", markersize=5, zorder=4)

        # cue 参考线
        self._ax.axvline(x=0, color="#3498db", alpha=0.25, linewidth=2, zorder=2)

        self._ax.set_yticks(range(1, n + 1))
        self._ax.set_yticklabels(y_labels, fontsize=6)
        # 空图例做标识
        from matplotlib.lines import Line2D
        legend_elements = [
            Line2D([0], [0], marker="o", color="w", markerfacecolor="#2ecc71", markersize=6, label="舔+奖励"),
            Line2D([0], [0], marker="o", color="w", markerfacecolor="#e67e22", markersize=6, label="舔+错过"),
            Line2D([0], [0], marker="D", color="w", markerfacecolor="#e74c3c", markersize=6, label="给水时刻"),
        ]
        self._ax.legend(handles=legend_elements, fontsize=6, loc="upper right",
                        ncol=3, framealpha=0.5)

        self._canvas.draw()
