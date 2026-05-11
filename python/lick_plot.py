"""嵌入式 matplotlib 舔水时间线。

单轴时间线：X 轴 = 实验时间（秒）。
每个试次用彩色线段标出窗口期，cue/给水 和 舔水 事件用标记标出。
"""

from collections import deque

import matplotlib
matplotlib.use("TkAgg")

import matplotlib.font_manager as fm
_cjk = ['Microsoft YaHei', 'SimHei', 'Noto Sans CJK SC']
_avail = {f.name for f in fm.fontManager.ttflist}
for _f in _cjk:
    if _f in _avail:
        matplotlib.rcParams['font.sans-serif'] = [_f, 'DejaVu Sans']
        break
matplotlib.rcParams['axes.unicode_minus'] = False

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure


class LickPlot:
    def __init__(self, parent):
        self._trials = deque(maxlen=200)
        self._fig = Figure(figsize=(6, 1.8), dpi=100)
        self._fig.subplots_adjust(left=0.08, right=0.96, top=0.88, bottom=0.20)

        self._ax = self._fig.add_subplot(111)
        self._ax.set_xlabel("时间 (s)", fontsize=8)
        self._ax.set_yticks([])
        self._ax.tick_params(labelsize=7)

        self._canvas = FigureCanvasTkAgg(self._fig, master=parent)
        self._canvas_widget = self._canvas.get_tk_widget()

    @property
    def widget(self):
        return self._canvas_widget

    def add_trial(self, trial_result):
        self._trials.append(trial_result)
        self._redraw()

    def clear(self):
        self._trials.clear()
        self._redraw()

    def _redraw(self):
        self._ax.clear()
        self._ax.set_xlabel("时间 (s)", fontsize=8)
        self._ax.set_yticks([])

        if not self._trials:
            self._canvas.draw()
            return

        t0 = self._trials[0].cue_time or 0
        rewarded = 0
        missed = 0

        for tr in self._trials:
            if tr.cue_time is None:
                continue
            t_cue = tr.cue_time - t0

            # 试次窗口底色
            if tr.outcome == "REWARDED":
                rewarded += 1
                self._ax.axvspan(t_cue, t_cue + 2.5, alpha=0.22, color="#4CAF50", linewidth=0)
            else:
                missed += 1
                self._ax.axvspan(t_cue, t_cue + 2.5, alpha=0.22, color="#F44336", linewidth=0)

            # Cue+给水 标记
            self._ax.plot(t_cue, 1, "v", color="#1565C0", markersize=7,
                          zorder=5, markeredgecolor="white", markeredgewidth=0.5)

            # 舔水标记：首次实心 ●，后续空心 ○
            licks = getattr(tr, 'lick_times', None)
            if licks is None and getattr(tr, 'lick_time', None) is not None:
                licks = [tr.lick_time]
            if licks:
                for j, lt in enumerate(licks):
                    tx = lt - t0
                    if j == 0:
                        self._ax.plot(tx, 1, "o", color="#1B5E20", markersize=8,
                                      zorder=6, markeredgecolor="white", markeredgewidth=1)
                    else:
                        self._ax.plot(tx, 1, "o", markerfacecolor="none",
                                      markeredgecolor="#4CAF50", markersize=7,
                                      zorder=6, markeredgewidth=1.2)

            # ITI 舔水：灰色空心圆
            iti_licks = getattr(tr, 'iti_lick_times', None)
            if iti_licks:
                for lt in iti_licks:
                    tx = lt - t0
                    self._ax.plot(tx, 0.5, "o", markerfacecolor="none",
                                  markeredgecolor="#999999", markersize=5,
                                  zorder=4, markeredgewidth=1)

        # 图例
        from matplotlib.lines import Line2D
        legend_elements = [
            Line2D([0], [0], marker='v', color='w', markerfacecolor='#1565C0',
                   markersize=7, label='Cue'),
            Line2D([0], [0], marker='o', color='w', markerfacecolor='#1B5E20',
                   markersize=7, label='首次舔'),
            Line2D([0], [0], marker='o', color='w', markerfacecolor='none',
                   markeredgecolor='#4CAF50', markersize=7, label='后续舔'),
            Line2D([0], [0], marker='o', color='w', markerfacecolor='none',
                   markeredgecolor='#999999', markersize=5, label='ITI舔'),
        ]
        self._ax.legend(handles=legend_elements, fontsize=6,
                        loc="upper right", framealpha=0.7, ncol=4)

        total = rewarded + missed
        rate = f"{rewarded*100//max(1,total)}%" if total else "--"
        self._ax.set_title(
            f"试次: {total}  舔水: {rewarded}  错过: {missed}  命中率: {rate}",
            fontsize=8, loc="left", fontweight="normal", color="#555555"
        )

        self._ax.set_ylim(0.3, 1.7)
        max_t = max((t.cue_time - t0 + 3) for t in self._trials if t.cue_time) if self._trials else 10
        self._ax.set_xlim(-1, max(8, max_t))

        self._canvas.draw()
