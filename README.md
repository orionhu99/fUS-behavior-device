# Head-fixed fUS behavior device control

整合式头部固定小鼠行为实验控制装置，兼容单光子/双光子/fUS 成像。

核心功能：
- **Cue-给水同步协议**：8kHz cue（PC 3.5mm 音响）+ 给水同时触发 → 2s 舔水窗 → 舔即记录 / 超时 MISS → 随机 ITI
- **电容舔水检测**（MPR121），直接寄存器读写，MDEBUG/THR 命令可调灵敏度
- **TTL 输出**：reward / lick / sync，对接成像采集系统
- **USB 摄像头录像 + 帧时间戳**，预览/录像独立切换，协议运行时自动录像
- **模块化水嘴支架**，预留食槽替换接口
- **PC 端 GUI**：参数设置、协议控制、时间轴舔水图表、事件日志

## File layout

```
arduino/
  water_lick_ttl_controller/water_lick_ttl_controller.ino  ← Water Nano 固件
  spout_motor_controller/spout_motor_controller.ino        ← Motor Nano 固件
  dianji/dianji.ino                                        ← 旧版电机测试（参考）
  sketch_apr25b/sketch_apr25b.ino                          ← 旧版给水测试（参考）
bpod/
  ExternalCueHiFi8kHz/ExternalCueHiFi8kHz.m                ← Bpod HiFi cue 协议
python/
  device_control_app.py     ← 主应用入口
  protocol_engine.py        ← 试次状态机
  gui_panels.py             ← GUI 面板组件
  lick_plot.py              ← matplotlib 舔水时间线
  config_manager.py         ← 协议配置 JSON 读写
  requirements.txt
  protocol_configs/         ← 保存的协议配置文件
      default.json
*.SLDPRT / *.STL / *.STEP  ← 3D 打印模型文件
```

## 给水协议

### 流程

```
IDLE → (▶ 运行) → ITI → PRECUE(200ms) → CUE(80ms, 8kHz) → 舔水窗口(3s)
                                                               ├─ 舔水 → 立即给水(400ms) → POST_REWARD(500ms) → ITI
                                                               └─ 超时 → 跳过(MISS) → ITI
```

- **Cue**：Water Nano D11 脉冲 TTL → Bpod BNC1 → HiFi 模块播放 8kHz tone
- **舔水窗口**：Nano 收到 `WINDOW dur reward` 命令后自治执行——监测 MPR121，舔到立即开泵，超时则跳过
- 关键延迟路径（舔→给水）在 Nano 上本地完成，不经 USB

### 可调参数

| 参数 | 默认值 | 说明 |
|---|---|---|
| `cue_duration_ms` | 80 | 8kHz 声音时长 |
| `precue_ms` | 200 | cue 前静默期（设 0 跳过） |
| `window_duration_ms` | 3000 | 舔水检测时间窗 |
| `reward_dose_ms` | 400 | 泵运行时长 |
| `post_reward_ms` | 500 | 给水后消耗期 |
| `iti_min_s` / `iti_max_s` | 20 / 60 | ITI 均匀随机范围 |
| `max_trials` | 200 | 最大试次数（0=不限） |
| `session_timeout_s` | 3600 | 最长会话时长 |

所有参数通过 GUI 调整，可保存/加载为 JSON 配置文件。

---

## Serial commands

### Water Nano

```
WATER [ms]           → 手动给水（含 reward TTL + cue TTL）
DOSE ms              → 设定默认剂量
PUMP ON / OFF        → 泵持续开/关
STOP                 → 停止泵 + 取消窗口模式
TTLMS ms             → 设定 TTL 脉宽
SYNCMS ms            → 设定同步脉冲间隔
CUE                  → 仅脉冲 D11 cue TTL（不启动泵）
WINDOW dur reward    → 启动舔水自治窗口（dur=窗口时长ms, reward=给水量ms）
WINDOW_STOP          → 取消当前窗口
STATUS / HELP
```

### Motor Nano（不变）

```
STEP signed_steps    GOTO position       F / B
JOG F / JOG B        STOP
ENABLE / DISABLE     SPEED microseconds
ZERO                 STATUS / HELP
```

---

## 接线（完整）

---

### 系统接线总览

```
┌─────────────────────────────────────────────────────────────────────────┐
│                               PC (USB Hub)                              │
│  USB1: Water Nano  │  USB2: Motor Nano  │  USB3: Bpod  │  USB4: 摄像头  │
└────┬──────────┬────┴──────────┬─────────┴──────┬───────┴──────┬────────┘
     │          │               │                │              │
┌────▼──┐  ┌────▼──────────┐  ┌▼─────────┐  ┌───▼──────┐  ┌───▼───┐
│ Water │  │   Motor Nano  │  │   Bpod   │  │  USB 摄  │  │ 水瓶  │
│ Nano  │  │               │  │  + HiFi  │  │  像头   │  │       │
│       │  │               │  │          │  │          │  │   │   │
│ D2─按钮│  │ D2─STEP─驱动板│  │ BNC1◄───┼──┼─D11(Cue) │  │   │   │
│ D3─LED │  │ D3─DIR──驱动板│  │     ┌───┼──┼─D8 (Rew) │  │   │   │
│ D5─MOS─┼──┼─蠕动泵       │  │ HiFi┼音响│  │ D9 (Lick)│  │  硅胶管─┤
│ D8─BNC─┼──┼─成像系统     │  │     │   │  │ D10(Sync)│  │       │   │
│ D9─BNC─┼──┼─成像系统     │  │     │   │  │          │  │   ┌───▼──┐│
│ D10─BNC┼──┼─成像系统     │  └─────┘   │  └──────────┘  │   │蠕动泵││
│ D11────┼──┼─Bpod BNC1   │            │               │   └──┬───┘│
│ A4─SDA─┼──┼─MPR121      │            │               │      │    │
│ A5─SCL─┼──┼─MPR121      │            │               │  外部电源 │
│        │  │             │            │               └──────────┘
│ 3V3/GND│  │ D4─ENA─驱动板│
│   ┤    │  │             │          ┌──────────────┐
│ MPR121 │  │ 5V/GND──驱动板│          │ 成像采集系统  │
│  E0    │  │             │          │ BNC Inputs:  │
│  ┤     │  │ 电机电源──驱动板│          │  Rew  Lick  │
│ 舔水管 │  │ 电机A/B──步进电机│         │  Sync Cue   │
└────────┘  └──────┬──────┘          └──────────────┘
                   │
              ┌────▼────┐
              │ 步进电机 │
              │ + 滑台  │
              └────┬────┘
                   │
              ┌────▼────┐
              │ 水嘴支架 │
              │(模块化) │
              └─────────┘
```

---

### 一、Water Nano 接线

Water Nano 是主控，负责蠕动泵、舔水检测、所有 TTL 输出。**在 Arduino IDE 中刷入 `arduino/water_lick_ttl_controller/` 固件。**

#### 1.1 引脚全表

| Nano 引脚 | 方向 | 连接到 | 线材 | 备注 |
|---|---|---|---|---|
| **D2** | 输入 (INPUT_PULLUP) | 轻触按钮一端，按钮另一端接 GND | 杜邦线 2P | 手动触发给水 |
| **D3** | 输出 | LED 正极（串 220Ω 电阻），LED 负极接 GND | 杜邦线 | 泵运行指示 |
| **D5** | 输出 | 三极管基极（串 1kΩ 电阻）或 MOSFET SIG 端 | 杜邦线 | 泵开关信号（HIGH=开） |
| **D8** | 输出 | BNC 母座中心针（Reward TTL） | 屏蔽线/杜邦线 | → 成像采集系统 |
| **D9** | 输出 | BNC 母座中心针（Lick TTL） | 屏蔽线/杜邦线 | → 成像采集系统 |
| **D10** | 输出 | BNC 母座中心针（Sync TTL） | 屏蔽线/杜邦线 | → 成像采集系统 |
| **D11** | 输出 | Bpod BNC1 中心针 | 屏蔽线/杜邦线 | Cue TTL → Bpod |
| **A4 / SDA** | I2C | MPR121 SDA 引脚 | 杜邦线母-母 | I2C 数据 |
| **A5 / SCL** | I2C | MPR121 SCL 引脚 | 杜邦线母-母 | I2C 时钟 |
| **5V** | 电源输出 | MPR121 VIN（若用 5V 供电版本） | 杜邦线 | 或接 3.3V |
| **3.3V** | 电源输出 | MPR121 VCC（推荐） | 杜邦线 | 噪声更小 |
| **GND** | 共地 | **所有以下设备的 GND**：MPR121、MOSFET 模块、BNC 外壳、Bpod GND | 多股杜邦线 | **最关键的单根线** |
| **VIN / USB** | 电源输入 | PC USB 口（供电 + 串口通信） | USB Mini-B 线 | 直接用 USB 供电即可 |

#### 1.2 手动按钮接线

```
Nano D2 ────┬──── 轻触按钮 ──── GND
            │
        (内部 INPUT_PULLUP，无需外接上拉电阻)
```

线序：D2 → 按钮一脚，按钮另一脚 → Nano GND。按下时 D2 读到 LOW，松开读到 HIGH。

#### 1.3 状态 LED 接线

```
Nano D3 ──── 220Ω 电阻 ──── LED 正极（长脚）
LED 负极（短脚） ──── Nano GND
```

#### 1.4 蠕动泵驱动 —— 方式 A：NPN 三极管（推荐，简单可靠）

```
        5V ───────────── 蠕动泵 +
        Nano D5 ── 1kΩ ── 三极管 Base (如 S8050 / 2N2222)
        蠕动泵 - ──────── 三极管 Collector
        Nano GND ─────── 三极管 Emitter

        三极管引脚（TO-92 封装，平面朝自己，脚朝下）：
                  ┌─────┐
        Collector │  ·  │  ← 接泵-
           Base   │  ·  │  ← 接 1kΩ → D5
         Emitter  │  ·  │  ← 接 GND
                  └─────┘
```

- D5 HIGH → 三极管导通 → 泵运转
- D5 LOW → 三极管截止 → 泵停止
- 泵两端反向并联一个 1N4007 续流二极管（带环一端接泵+，另一端接泵-），防止关断时反向电压击穿三极管
- 三极管选型：泵电流 < 500mA 用 S8050 即可；更大电流用 TIP120 达林顿管

#### 1.4 蠕动泵驱动 —— 方式 B：MOSFET 模块

```
┌─────────────┐
│  外部电源    │      注意：泵的电压/电流不要超过
│  (如 12V)   │      MOSFET 模块的额定值
│  +      -   │
│  │      │   │
│  │      └───┼──────────────┐
│  │          │              │
│  │    ┌─────▼──────┐      │
│  │    │ MOSFET 模块 │      │
│  │    │  DC+   DC- │      │
│  │    │  IN   GND  │      │
│  │    │  OUT+ OUT- │      │
│  │    └──┬───┬──┬──┘      │
│  │       │   │  │         │
│  └───────┼───┘  │         │
│          │      │         │
│    ┌─────▼──────┼──┐      │
│    │  蠕动泵     │  │      │
│    │   +    -   │  │      │
│    │   │    │   │  │      │
│    │   │    └───┼──┘      │
│    │   │        │         │
│    └───┼────────┘         │
│        │                  │
└────────┘                  │
                            │
    Nano D5 ──── IN         │
    Nano GND ─── GND ───────┘
```

接线步骤：
1. 外部电源 + 接 MOSFET 模块 DC+
2. 外部电源 - 接 MOSFET 模块 DC-
3. 蠕动泵 + 接 MOSFET 模块 OUT+
4. 蠕动泵 - 接 MOSFET 模块 OUT-
5. Nano D5 接 MOSFET 模块 IN（信号输入端）
6. **Nano GND 接 MOSFET 模块 GND（必须共地）**

> ⚠️ 泵是感性负载，关断时会产生反向电动势。如果 MOSFET 模块不带保护二极管，在泵两端并联一个续流二极管（如 1N4007）：阴极（带环一端）接泵+，阳极接泵-。

---

### 二、MPR121 电容舔水检测接线

#### 2.1 MPR121 → Water Nano

```
MPR121 VCC  ──── Nano 3.3V  （推荐 3.3V，噪声更低）
MPR121 GND  ──── Nano GND
MPR121 SDA  ──── Nano A4
MPR121 SCL  ──── Nano A5
MPR121 ADD  ──── 不接（默认 I2C 地址 0x5A）
MPR121 IRQ  ──── 不接（固件用轮询方式）
MPR121 E0   ──── 金属舔水管（见下方隔离说明）
```

#### 2.2 MPR121 电极隔离（最关键！）

```
┌──────────────────────────────────────────────────┐
│                  3D 打印支架                      │
│                                                  │
│   ┌──────────────────────────────┐              │
│   │  PTFE 绝缘套管（包住水管）     │              │
│   │  ┌────────────────────┐      │              │
│   │  │  金属舔水管（不锈钢）│      │              │
│   │  │  █████████████████ │      │              │
│   │  │  █████████████████ │      │              │
│   │  └──────────┬─────────┘      │              │
│   │             │ 仅管尖 1−2mm    │              │
│   │             │ 暴露供舔舐      │              │
│   └─────────────┼────────────────┘              │
│                 │                                │
│       MPR121 E0 ┘  (焊接或屏蔽线夹紧)              │
│                                                  │
│   水管全程不得与支架/电机/Z台/平台有金属接触        │
└──────────────────────────────────────────────────┘
```

操作步骤：
1. 截一段 PTFE 管（外径略小于支架孔），长度略长于支架厚度
2. 将 PTFE 管套在不锈钢水管外面，穿过 3D 打印支架孔
3. 不锈钢水管管体包覆热缩管，加热收缩，仅留管尖 1-2mm 裸露
4. MPR121 E0 引脚焊接一段细导线（或屏蔽线内芯），另一端用导电胶/焊锡/鳄鱼夹连接到不锈钢水管
5. 用万用表电阻档确认：水管与光学平台/电机外壳/支架之间的电阻 > 10MΩ（无穷大）

> 如果漏电（水管和大地导通），MPR121 会读到大量噪声，舔水检测失效。**这步做不好，整个系统不能用。**

---

### 三、Motor Nano 接线

Motor Nano 控制安装在手动 Z 台上的步进电机，用于微调水嘴位置。**在 Arduino IDE 中刷入 `arduino/spout_motor_controller/` 固件。**

#### 3.1 引脚全表

| Nano 引脚 | 方向 | 连接到 | 线材 | 备注 |
|---|---|---|---|---|
| **D2** | 输出 | 驱动板 STEP- (或 PUL-) | 杜邦线 | 步进脉冲 |
| **D3** | 输出 | 驱动板 DIR- | 杜邦线 | 方向信号 |
| **D4** | 输出 | 驱动板 ENA- | 杜邦线 | 使能（低电平有效） |
| **5V** | 电源输出 | 驱动板 STEP+/DIR+/ENA+ | 杜邦线 3 根 | **仅光耦驱动板需此接法** |
| **GND** | 共地 | 驱动板信号 GND（如有） | 杜邦线 | 非光耦驱动板需共地 |
| **VIN / USB** | 电源输入 | PC USB 口（供电 + 串口通信） | USB Mini-B 线 | |

#### 3.2 步进电机驱动板接线 —— 方式 A：光耦输入驱动板（如 TB6600 / DM542 / DM556）

这些驱动板的信号输入是光耦隔离的，推荐**共阳极接法**：

```
        Nano 5V ───┬─── 驱动板 PUL+  ┐
                    ├─── 驱动板 DIR+   │ 三个正端全部接 Nano 5V
                    └─── 驱动板 ENA+  ┘

        Nano D2 ─────── 驱动板 PUL-
        Nano D3 ─────── 驱动板 DIR-
        Nano D4 ─────── 驱动板 ENA-

        外部电源 + ───── 驱动板 VCC（电机电源输入，如 24V）
        外部电源 - ───── 驱动板 GND

        驱动板 A+ ────── 步进电机 A+（通常红色）
        驱动板 A- ────── 步进电机 A-（通常蓝色）
        驱动板 B+ ────── 步进电机 B+（通常绿色）
        驱动板 B- ────── 步进电机 B-（通常黑色）
```

> 注意：共阳接法时 Nano GND **不需要**接驱动板信号 GND。驱动板的信号地和功率地通常内部隔离。

#### 3.3 步进电机驱动板接线 —— 方式 B：普通逻辑输入驱动板（如 A4988 / DRV8825 / TMC2208）

```
        驱动板 VDD  ───── Nano 5V
        驱动板 GND  ───── Nano GND

        驱动板 STEP ───── Nano D2
        驱动板 DIR  ───── Nano D3
        驱动板 ENABLE ─── Nano D4

        驱动板 VMOT ───── 外部电源 +
        驱动板 GND  ───── 外部电源 -

        驱动板 1A ─────── 步进电机 A+
        驱动板 1B ─────── 步进电机 A-
        驱动板 2A ─────── 步进电机 B+
        驱动板 2B ─────── 步进电机 B-
```

> 固件默认 `enableActiveLow = true`。如果你的驱动板是高电平使能（如某些 TMC 系列），打开 `.ino` 文件把第 8 行改成 `const bool enableActiveLow = false;`。

---

### 四、TTL 信号输出接线

Water Nano 的 D8/D9/D10/D11 输出 5V TTL 脉冲。需要接到成像系统或用 BNC 接口标准化。

#### 4.1 TTL → BNC 母座（接成像系统）

自制 BNC 转接线（每路 TTL 做一根）：

```
Nano D8/D9/D10/D11 ──────── BNC 母座中心针（信号）
Nano GND           ──────── BNC 母座外壳/屏蔽层（地）
```

做法：
1. 取一段同轴电缆或双绞屏蔽线
2. 内芯一端接 Nano 排针（用杜邦母头压接或焊接），另一端焊 BNC 母座中心针
3. 屏蔽层一端接 Nano GND，另一端焊 BNC 母座外壳
4. BNC 母座固定在 3D 打印面板或铝盒上，用 BNC 公-公线连到成像系统

#### 4.2 TTL 信号分工

| Nano 引脚 | 事件 | 脉冲宽度 | 目标设备 |
|---|---|---|---|
| **D8** | Reward（给水开始） | `ttlPulseMs` (默认 10ms) | 成像系统 AI 通道 1 |
| **D9** | Lick（舔水） | `ttlPulseMs` (默认 10ms) | 成像系统 AI 通道 2 |
| **D10** | Sync（同步） | `ttlPulseMs` (默认 10ms) | 成像系统 AI 通道 3 |
| **D11** | Cue（8kHz 触发） | `ttlPulseMs` (默认 10ms) | Bpod BNC1 输入 |

> 成像系统如果是 BNC 接口，直接对接。如果是 DAQ 端子排（如 NI 68-Pin），做 BNC→端子排转接线。

#### 4.3 TTL 电平兼容性

- Nano 输出 5V TTL，兼容 3.3V 和 5V 逻辑
- Bpod r2/r2+ BNC 输入接受 3-5V TTL，光隔离，直接可接
- 如果目标设备只接受 3.3V：在信号线上串 1kΩ 限流电阻 + 对地接 3.3V 稳压管

---

### 五、Bpod + HiFi 模块接线

#### 5.1 Bpod → PC

```
Bpod USB-B ──── PC USB 口（供电 + MATLAB 通信）
```

#### 5.2 HiFi 模块 → Bpod

```
HiFi 模块 ──── Bpod 机箱背面模块接口（通过扁平排线或专用接口）
```

> 在 Bpod Console GUI 中确认模块识别为 `HiFi1`，USB 端口号写入 `BpodSystem.ModuleUSB.HiFi1`。

#### 5.3 HiFi 模块 → 音响

```
HiFi 模块音频输出 (3.5mm 或 RCA) ──── 有源音箱 Line In
```

> 使用有源音箱（自带功放）。如果只有无源音箱，中间需要加功放模块。HiFi 模块输出是线路电平，直接推不动无源音箱。

#### 5.4 Bpod BNC1 输入 ← Water Nano Cue TTL

```
Water Nano D11 ──── BNC 中心针 ──── Bpod BNC1 输入
Water Nano GND ──── BNC 外壳     ──── Bpod GND（如 BNC 外壳已内部接地则不必额外接）
```

#### 5.5 运行 Bpod 端

在 MATLAB 中：
```matlab
cd('D:\Research\fUS\device\bpod\ExternalCueHiFi8kHz')
ExternalCueHiFi8kHz
```

Bpod 会进入等待状态，每次 Water Nano D11 发来 TTL 脉冲，HiFi 就播放 80ms 的 8kHz tone。

---

### 六、USB 摄像头接线

```
USB 摄像头 ──── PC USB 口
```

- 在 GUI "连接"面板中输入摄像头索引（通常是 `0`，如有多个摄像头试 `1`、`2`）
- 点击"开始录像"即开始录制并生成帧时间戳 CSV
- 摄像头对准小鼠侧面/正面，记录舔水和行为

---

### 七、PC 端最终连接汇总

| 设备 | 接口 | PC 端口 |
|---|---|---|
| Water Nano | USB Mini-B | USB 1 |
| Motor Nano | USB Mini-B | USB 2 |
| Bpod | USB-B | USB 3 |
| USB 摄像头 | USB-A | USB 4 |

> 建议用一个 **有源 USB 3.0 Hub**（4 口以上），固定在光学平台边缘，只出一根线到 PC。减少桌面杂乱。

---

### 八、电源分配

| 用电设备 | 供电方式 | 电压 | 备注 |
|---|---|---|---|
| Water Nano | PC USB | 5V | 同时通信 |
| Motor Nano | PC USB | 5V | 同时通信 |
| MPR121 | Water Nano 3.3V | 3.3V | Nano 直接供电 |
| 蠕动泵 | 外部电源 → MOSFET | 12V（视泵规格） | **不要从 Nano 取电** |
| 步进电机 | 外部电源 → 驱动板 | 12-24V（视电机/驱动板） | **不要从 Nano 取电** |
| 步进驱动板逻辑 | Nano 5V（光耦型） | 5V | 电流很小 |
| Bpod | 自带电源适配器 | — | 官配 |
| 有源音箱 | 自带电源/USB | — | |

> 建议用一个双路输出开关电源（如 24V/12V 双路），或两个独立电源适配器分别给蠕动泵和步进电机供电。

---

### 九、上电顺序

1. 检查所有接线（特别确认：泵和电机的供电**没有**接到 Nano）
2. MPR121 隔离用万用表确认（水管对地电阻无穷大）
3. 打开蠕动泵和步进电机的外部电源
4. 打开 Bpod 电源
5. 所有 USB 插入 PC（或 USB Hub 上电）
6. 打开有源音箱，音量调至适中
7. 在 Arduino IDE 中确认两个 Nano 都识别到正确的 COM 口
8. 启动 Bpod MATLAB 协议 `ExternalCueHiFi8kHz`
9. 启动 Python GUI `python python\device_control_app.py`
10. 在 GUI 中依次连接 Water Nano 和 Motor Nano
11. 连接成功后，先用手动模式测试：手动给水确认泵和 TTL 正常，电机微调确认运动正常
12. 一切正常后，加载协议配置，点击 ▶ 运行

---

### 十、接地策略

```
                    ┌─── 光学平台（金属）─── 接大地（如有）
                    │
    ┌───────────────┼────────────────────────┐
    │               │                        │
    │  Water Nano GND ─┬─ MPR121 GND         │
    │                  ├─ MOSFET 模块 GND     │
    │                  ├─ BNC 外壳 (x4)      │
    │                  └─ Bpod BNC 外壳      │
    │                                        │
    │  Motor Nano GND ─── 驱动板信号 GND      │
    │  （光耦型驱动板则无需）                  │
    │                                        │
    │  外部电源 - ──┬─ MOSFET DC-            │
    │              └─ 驱动板功率 GND          │
    │                                        │
    │  所有设备通过 USB 电缆屏蔽层在 PC 端单点共地 │
    └────────────────────────────────────────┘
```

> 接地原则：所有信号 GND（Nano、MPR121、MOSFET 信号侧、TTL 目标设备）必须连通。不要形成地环路——在 PC USB 端单点汇聚即可。如果出现 50Hz 工频干扰在 MPR121 上，检查是否有多点接地。

---

## PC 端使用

### 安装

```powershell
pip install -r python\requirements.txt
```

### 运行

```powershell
python python\device_control_app.py
```

### GUI 面板

| 面板 | 功能 |
|---|---|
| 连接 | COM 端口选择、Nano 连接、摄像头控制、输出目录 |
| 手动控制 | 剂量设定、手动给水、泵开关、TTL/同步参数、PC 测试音 |
| 电机控制 | 大小步进微调、速度设定、归零 |
| 协议控制 | 全部协议参数、运行/暂停/停止、配置保存加载、状态显示 |
| 舔水时间线 | 实时试次栅格图 + 累积直方图 |
| 事件日志 | 所有串口事件 + 主机时间戳 |

### 输出文件

```
recordings/
  device_events_*.csv        ← 全事件日志（串口 + 主机）
  behavior_*.avi             ← 摄像头视频
  behavior_*_frames.csv      ← 视频帧时间戳
```

---

## 8kHz Cue 声音

**主方案**：PC 3.5mm 音频口 → 有源音箱。协议进入 CUE 阶段时自动播放 8kHz 纯音（WAV 生成 + winsound 播放），无需 Bpod/HiFi 模块。

手动测试：GUI "手动控制" 面板勾选 "PC 8kHz"，点"给水"时同步播放 cue 音。

> 如需 Bpod/HiFi 方案（更低延迟），D11 cue TTL 仍然保留，可接 Bpod BNC1 输入，运行 `bpod/ExternalCueHiFi8kHz/ExternalCueHiFi8kHz.m`。PC 音频和 TTL cue 可同时工作互不冲突。

---

## 时间对齐

三层对齐策略：

1. Arduino 串口 CSV 中的 `millis()` 事件时间戳
2. 主机 `perf_counter` 时间戳（设备日志 + 视频帧日志）
3. 物理 TTL 线接入成像/采集系统（D8/D9/D10/D11）

正式实验时保持 D10 sync TTL 全程运行。

---

## 3D 打印件

| 零件 | 文件 | 说明 |
|---|---|---|
| 散热风扇导管 | `tube-fan3.0-4.3.STL` | |
| 动物固定兜 | `兜子.STEP` | 头部固定小鼠 |
| 给水外壳 | `给水1.0外壳.SLDPRT` | 电子盒外壳 |
| 水嘴模块底板（待设计） | — | 安装于电机滑台，带燕尾槽快拆接口 |
| 水嘴支架模块（待设计） | — | PTFE 绝缘套管、可调角度、快拆锁紧 |
| 食槽模块（预留接口） | — | 同底板燕尾槽规格 |

---

## 硬件清单

| 组件 | 说明 |
|---|---|
| PC (Windows) | USB 接口 ×4+ |
| Arduino Nano ×2 | Water + Motor |
| MPR121 电容模块 | I2C 接口，Adafruit 库 |
| 蠕动泵 + MOSFET 驱动 | 外部电源供电 |
| 步进电机 + 驱动板 | TB6600/DM 系列 |
| 手动 Z 台 + 电机滑台 | 水嘴微调 |
| 有源音箱 | PC 3.5mm 音频口连接 |
| Bpod + HiFi 模块（可选） | 低延迟 cue 播放备选 |
| USB 摄像头 | OpenCV 兼容 |
| 光学平台 | 面包板，M6 或 1/4"-20 孔距 |
| 3D 打印件 | 如上表 |
| 金属舔水管 | 不锈钢，与支架绝缘 |
| PTFE 管 / 热缩管 | MPR121 隔离 |
| BNC 线 / 杜邦线 | TTL 连接 |
| 硅胶管 / 水瓶 | 水路 |
