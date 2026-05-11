"""Water Nano 单板测试脚本。

使用方式：
    python test_water_nano.py COM3

逐个测试：基础通信、泵控制、CUE、WINDOW 模式。
不依赖 GUI，适合刷完固件后快速验证。
"""

import sys
import time
import serial


def read_line(ser, timeout=2.0):
    """读取一行，带超时。"""
    deadline = time.time() + timeout
    buf = b""
    while time.time() < deadline:
        b = ser.read(1)
        if b:
            buf += b
            if b == b"\n":
                return buf.decode("utf-8", errors="replace").strip()
        else:
            time.sleep(0.005)
    return buf.decode("utf-8", errors="replace").strip() if buf else None


def cmd(ser, text, expect=None, wait=0.3):
    """发送命令，读取所有响应。"""
    ser.reset_input_buffer()
    ser.write((text + "\n").encode("ascii"))
    time.sleep(wait)
    lines = []
    while True:
        line = read_line(ser, timeout=0.2)
        if line is None or line == "":
            break
        lines.append(line)
    return lines


def test_header(title):
    print()
    print("=" * 60)
    print(f"  {title}")
    print("=" * 60)


def test_result(ok, msg=""):
    status = "✓ PASS" if ok else "✗ FAIL"
    print(f"  {status}  {msg}")


def main():
    if len(sys.argv) < 2:
        port = input("请输入 Water Nano COM 口 (如 COM3): ").strip()
    else:
        port = sys.argv[1]

    try:
        ser = serial.Serial(port, baudrate=115200, timeout=0.2)
    except Exception as e:
        print(f"无法打开 {port}: {e}")
        return

    print(f"已连接 {port}，等待 Nano 启动...")
    time.sleep(2)

    # 清初始输出
    ser.reset_input_buffer()
    while True:
        line = read_line(ser, timeout=0.5)
        if line is None or line == "":
            break
        print(f"  启动: {line}")

    all_pass = True

    # ── 测试 1: HELP ──
    test_header("1. HELP 命令")
    lines = cmd(ser, "HELP")
    ok = any("Commands:" in l for l in lines)
    for l in lines:
        print(f"  {l}")
    test_result(ok, "应列出所有命令（含 CUE, WINDOW）")
    all_pass = all_pass and ok

    # ── 测试 2: STATUS ──
    test_header("2. STATUS 命令")
    lines = cmd(ser, "STATUS")
    ok = any("STATUS" in l for l in lines)
    for l in lines:
        print(f"  {l}")
    test_result(ok, "应返回 dose_ms, pump, mpr121, sync_ms")
    all_pass = all_pass and ok

    # ── 测试 3: 泵控制 ──
    test_header("3. 泵控制 (PUMP ON/OFF)")
    print("  >>> PUMP ON (运行 1 秒)")
    cmd(ser, "PUMP ON")
    time.sleep(1.0)
    lines = cmd(ser, "PUMP OFF")
    ok = any("PUMP" in l and "OFF" in l for l in lines)
    for l in lines:
        print(f"  {l}")
    test_result(ok, "泵应短暂运行 1 秒，LED 亮起")
    all_pass = all_pass and ok

    # ── 测试 4: 手动给水 ──
    test_header("4. 手动给水 (WATER 500)")
    print("  >>> WATER 500 (给水 500ms)")
    lines = cmd(ser, "WATER 500")
    ok = any("WATER" in l and "500" in l for l in lines)
    for l in lines:
        print(f"  {l}")
    test_result(ok, "泵应运行 500ms，D8/D11 各输出一个 TTL 脉冲")
    all_pass = all_pass and ok

    # ── 测试 5: 剂量设定 ──
    test_header("5. 剂量设定 (DOSE 800)")
    lines = cmd(ser, "DOSE 800")
    ok = any("DOSE_MS" in l and "800" in l for l in lines)
    for l in lines:
        print(f"  {l}")
    test_result(ok)
    # 改回默认
    cmd(ser, "DOSE 400")
    all_pass = all_pass and ok

    # ── 测试 6: CUE 命令 ──
    test_header("6. CUE 命令 (仅 TTL，不启动泵)")
    print("  >>> CUE")
    lines = cmd(ser, "CUE")
    ok = any("CUE" in l and "1" in l for l in lines)
    for l in lines:
        print(f"  {l}")
    test_result(ok, "D11 应输出一个 TTL 脉冲，泵不应启动")
    all_pass = all_pass and ok

    # ── 测试 7: WINDOW 模式（无 MPR121 时手动触发） ──
    test_header("7. WINDOW 窗口模式 (3 秒窗口，400ms 给水)")
    print("  >>> WINDOW 3000 400")
    lines = cmd(ser, "WINDOW 3000 400")
    ok_start = any("WINDOW_START" in l for l in lines)
    for l in lines:
        print(f"  {l}")
    test_result(ok_start, "窗口应启动")

    if ok_start:
        # 无 MPR121 时，窗口 3 秒后自动超时
        print("  等待 3 秒窗口超时...")
        time.sleep(3.5)
        lines = []
        while True:
            line = read_line(ser, timeout=0.3)
            if line is None or line == "":
                break
            lines.append(line)
        ok_missed = any("WINDOW_END" in l and "MISSED" in l for l in lines)
        for l in lines:
            print(f"  {l}")
        test_result(ok_missed, "无 MPR121 时应超时 MISSED")
        all_pass = all_pass and ok_missed

    # ── 测试 8: WINDOW_STOP ──
    test_header("8. WINDOW_STOP 手动取消窗口")
    cmd(ser, "WINDOW 10000 400")
    time.sleep(0.5)
    lines = cmd(ser, "WINDOW_STOP")
    ok = any("WINDOW_STOP" in l for l in lines)
    for l in lines:
        print(f"  {l}")
    test_result(ok)
    all_pass = all_pass and ok

    # ── 测试 9: TTL/SYNC 参数 ──
    test_header("9. TTL 和 Sync 参数")
    lines = cmd(ser, "TTLMS 20")
    ok1 = any("TTL_MS" in l and "20" in l for l in lines)
    for l in lines:
        print(f"  {l}")
    test_result(ok1, "TTL 脉宽设为 20ms")

    lines = cmd(ser, "SYNCMS 500")
    ok2 = any("SYNC_MS" in l and "500" in l for l in lines)
    for l in lines:
        print(f"  {l}")
    test_result(ok2, "同步间隔设为 500ms")
    all_pass = all_pass and ok1 and ok2

    # 恢复默认
    cmd(ser, "TTLMS 10")
    cmd(ser, "SYNCMS 1000")

    # ── 测试 10: 按钮 ──
    test_header("10. 手动按钮测试")
    print("  请按一下 D2 连接的按钮（5 秒内）...")
    lines = []
    deadline = time.time() + 5
    while time.time() < deadline:
        line = read_line(ser, timeout=0.3)
        if line:
            lines.append(line)
            if "WATER" in line:
                break
    ok = any("WATER" in l for l in lines)
    for l in lines:
        print(f"  {l}")
    test_result(ok, "按下按钮应触发一次 WATER")
    # 按钮测试失败不算关键故障
    if not ok:
        print("  (如果没按按钮或接线未完成，忽略此结果)")

    # ── 总结 ──
    test_header("测试总结")
    if all_pass:
        print("  ✓ 全部测试通过！Water Nano 固件运行正常。")
    else:
        print("  ⚠ 部分测试未通过，请检查接线和固件烧录。")

    ser.close()
    print(f"\n串口 {port} 已关闭。")


if __name__ == "__main__":
    main()
