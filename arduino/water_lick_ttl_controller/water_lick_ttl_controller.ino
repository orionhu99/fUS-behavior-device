#include <Wire.h>
#include <avr/wdt.h>

// Nano for water delivery, lick detection, and TTL event outputs.

const byte buttonPin = 2;
const byte ledPin = 3;
const byte pumpPin = 5;

const byte rewardTtlPin = 8;
const byte lickTtlPin = 9;
const byte syncTtlPin = 10;
const byte cueTtlPin = 11;

const byte lickElectrode = 0;

// ── 参数 ──
unsigned long doseMs = 400;
unsigned long ttlPulseMs = 10;
unsigned long lickRefractoryMs = 100;
unsigned long syncIntervalMs = 5000;

// ── MPR121 灵敏度（运行时可调）──
byte mprTouchThr = 8;     // 触摸阈值，越小越灵敏（范围 1-255，默认 12）
byte mprReleaseThr = 4;   // 释放阈值，应小于触摸阈值（默认 6）
int confirmDeltaMin = 5;  // 软件确认：abs(baseline-filtered) 最小变化量

// ── 状态 ──
bool pumpRunning = false;
bool autoMode = false;

// MPR121
byte mprAddr = 0x5A;
bool mpr121Ready = false;

// 舔水检测
bool lastTouched = false;
bool lickLatched = false;
unsigned long lastLickAt = 0;
unsigned long lastReleaseAt = 0;
unsigned long lickReleaseMs = 100;
int confirmCnt = 0;

// 窗口模式
bool windowMode = false;
unsigned long windowStartAt = 0;
unsigned long windowDurationMs = 0;
unsigned long windowRewardMs = 0;
bool windowRewarded = false;

// 计时
unsigned long pumpStopAt = 0;
unsigned long nextSyncAt = 0;
unsigned long rewardTtlOffAt = 0;
unsigned long lickTtlOffAt = 0;
unsigned long syncTtlOffAt = 0;
unsigned long cueTtlOffAt = 0;

char line[64];
byte lineIdx = 0;

// ═══════════════════════════════════════════════════════════
// MPR121 底层读写（绕过 Adafruit 库）
// ═══════════════════════════════════════════════════════════

static unsigned long lastMprRead = 0;
static bool i2cOk = true;

bool mprWrite(byte reg, byte val) {
  Wire.beginTransmission(mprAddr);
  Wire.write(reg);
  Wire.write(val);
  byte r = Wire.endTransmission();
  if (r != 0) { i2cOk = false; return false; }
  i2cOk = true; return true;
}

byte mprRead8(byte reg) {
  Wire.beginTransmission(mprAddr);
  Wire.write(reg);
  if (Wire.endTransmission(false) != 0) { i2cOk = false; return 0; }
  Wire.requestFrom((uint8_t)mprAddr, (uint8_t)1);
  byte v = Wire.available() ? Wire.read() : 0;
  i2cOk = true; return v;
}

uint16_t mprRead16(byte reg) {
  Wire.beginTransmission(mprAddr);
  Wire.write(reg);
  if (Wire.endTransmission(false) != 0) { i2cOk = false; return 0; }
  Wire.requestFrom((uint8_t)mprAddr, (uint8_t)2);
  uint16_t v = 0;
  if (Wire.available()) v = Wire.read();
  if (Wire.available()) v |= ((uint16_t)Wire.read() << 8);
  i2cOk = true; return v & 0x03FF;
}

void i2cRecover() {
  Wire.end();
  delay(5);
  Wire.begin();
  delay(5);
  i2cOk = true;
}

// ═══════════════════════════════════════════════════════════
// MPR121 手动初始化（不依赖 Adafruit 库的 begin）
// ═══════════════════════════════════════════════════════════

bool initMpr121() {
  Serial.println(F("--- MPR121 manual init ---"));

  // 1. I2C 扫描
  Serial.println(F("I2C scan:"));
  int found = 0;
  for (byte a = 1; a < 127; a++) {
    Wire.beginTransmission(a);
    if (Wire.endTransmission() == 0) {
      Serial.print(F("  0x")); Serial.println(a, HEX);
      found++;
    }
  }
  if (found == 0) {
    Serial.println(F("!! No I2C devices — check VCC/GND/SDA/SCL wiring"));
    return false;
  }

  // 2. 尝试 MPR121 地址
  byte addrs[] = {0x5A, 0x5B, 0x5C, 0x5D};
  mprAddr = 0;
  for (byte i = 0; i < 4; i++) {
    Wire.beginTransmission(addrs[i]);
    if (Wire.endTransmission() == 0) { mprAddr = addrs[i]; break; }
  }
  if (mprAddr == 0) {
    Serial.println(F("!! MPR121 not found at 0x5A-0x5D"));
    return false;
  }
  Serial.print(F("MPR121 at 0x")); Serial.println(mprAddr, HEX);

  // 3. 软复位
  mprWrite(0x80, 0x63);
  delay(10);

  // 4. 停止，开始配置
  mprWrite(0x5E, 0x00);
  delay(5);

  // 5. AFE 配置（Analog Front End）
  mprWrite(0x2B, 0x01); // MHD Rising
  mprWrite(0x2C, 0x01); // NHD Rising
  mprWrite(0x2D, 0x00); // NCL Rising
  mprWrite(0x2E, 0x00); // FDL Rising
  mprWrite(0x2F, 0x01); // MHD Falling
  mprWrite(0x30, 0x01); // NHD Falling
  mprWrite(0x31, 0xFF); // NCL Falling
  mprWrite(0x32, 0x02); // FDL Falling

  // 6. 触摸/释放阈值 — 只设电极 0
  mprWrite(0x41, mprTouchThr);   // E0 触摸阈值
  mprWrite(0x42, mprReleaseThr); // E0 释放阈值

  // 7. 去抖
  mprWrite(0x5B, 0x00); // 去抖 = 0（由软件处理）

  // 8. 配置寄存器
  mprWrite(0x5C, 0x10); // Config1: FFI=1 (28ms 首滤波), CDC=0, SFI=0, ESI=0
  mprWrite(0x5D, 0x20); // Config2: 0.5uA 充电, 0.5us 充电时间

  // 9. 使能电极 0（仅 E0，开启基线自动追踪）
  //    ECR bit[3:0] = 电即使能 + 基线追踪
  //    ECR bit[7:4] = 接近检测使能（不用）
  mprWrite(0x5E, 0x01);

  delay(200);

  // 10. 校验：回读 ECR
  byte ecr = mprRead8(0x5E);
  Serial.print(F("ECR = 0x")); Serial.println(ecr, HEX);
  if (ecr != 0x01) {
    Serial.println(F("!! ECR mismatch — configuration failed"));
    return false;
  }

  // 11. 读初始值
  uint16_t f0 = mprRead16(0x04);
  uint16_t b0 = mprRead16(0x1E);
  Serial.print(F("E0 raw filtered=")); Serial.print(f0);
  Serial.print(F(" baseline=")); Serial.print(b0);
  Serial.print(F(" diff=")); Serial.println((int16_t)b0 - (int16_t)f0);

  if (f0 == 0 && b0 == 0) {
    Serial.println("!! filtered=0 AND baseline=0 -- electrode may be floating");
    Serial.println("   Check: MPR121 E0 pin -> metal lick tube");
    Serial.println("   Check: tube insulation with multimeter");
  }

  Serial.println(F("--- MPR121 init done ---"));
  Serial.println("Send MDEBUG for live values, REGDUMP for register dump");
  return true;
}

// ═══════════════════════════════════════════════════
// 初始化
// ═══════════════════════════════════════════════════

void setup() {
  pinMode(buttonPin, INPUT_PULLUP);
  pinMode(ledPin, OUTPUT);
  pinMode(pumpPin, OUTPUT);
  pinMode(rewardTtlPin, OUTPUT);
  pinMode(lickTtlPin, OUTPUT);
  pinMode(syncTtlPin, OUTPUT);
  pinMode(cueTtlPin, OUTPUT);

  setPump(false);
  setAllTtlsLow();

  Serial.begin(115200);
  while (!Serial) {}

  // 看门狗：500ms 超时自动复位（防止 I2C 卡死导致永久死机）
  wdt_enable(WDTO_500MS);

  mpr121Ready = initMpr121();

  logEvent("READY", mpr121Ready ? "MPR121_OK" : "MPR121_MISSING");
  printHelp();
}

// ═══════════════════════════════════════════════════
// 主循环
// ═══════════════════════════════════════════════════

void loop() {
  wdt_reset();  // 喂狗
  const unsigned long now = millis();
  readSerial();
  readButton();
  readLick(now);
  updatePump(now);
  updateTtls(now);
  updateSync(now);
  updateWindow(now);
}

// ═══════════════════════════════════════════════════
// 串口命令
// ═══════════════════════════════════════════════════

void readSerial() {
  while (Serial.available() > 0) {
    char c = (char)Serial.read();
    if (c == '\n' || c == '\r') {
      if (lineIdx > 0) {
        line[lineIdx] = '\0';
        handleCommand(line);
        lineIdx = 0;
      }
    } else if (lineIdx < 63) {
      line[lineIdx++] = c;
    }
  }
}

void handleCommand(const char* cmd) {
  // 跳过前导空格
  while (*cmd == ' ' || *cmd == '\t') cmd++;
  int len = strlen(cmd);
  if (len == 0) return;

  // 转大写
  char upper[64];
  for (int i = 0; i <= len; i++) upper[i] = (cmd[i] >= 'a' && cmd[i] <= 'z') ? cmd[i] - 32 : cmd[i];

  if (strcmp(upper, "HELP") == 0)             printHelp();
  else if (strcmp(upper, "STATUS") == 0)      logEvent("STATUS", statusText());
  else if (strcmp(upper, "WATER") == 0)       startDose(doseMs);
  else if (strncmp(upper, "WATER ", 6) == 0)  startDose(atol(upper + 6));
  else if (strncmp(upper, "DOSE ", 5) == 0)   { doseMs = atol(upper + 5); logEvent("DOSE_MS", String(doseMs).c_str()); }
  else if (strcmp(upper, "PUMP ON") == 0)     { autoMode = true;  setPump(true);  logEvent("PUMP", "ON"); }
  else if (strcmp(upper, "PUMP OFF") == 0 || strcmp(upper, "STOP") == 0) {
    autoMode = false; pumpRunning = false; windowMode = false;
    setPump(false); logEvent("PUMP", "OFF");
  }
  else if (strcmp(upper, "CUE") == 0)         { pulseCueTtl(millis()); logEvent("CUE", "1"); }
  else if (strncmp(upper, "WINDOW ", 7) == 0) {
    char* sp1 = strchr(upper + 7, ' ');
    if (sp1) {
      windowDurationMs = atol(upper + 7);
      windowRewardMs = atol(sp1 + 1);
      windowMode = true; windowStartAt = millis(); windowRewarded = false;
      logEvent("WINDOW_START", (String(windowDurationMs) + "," + String(windowRewardMs)).c_str());
    }
  }
  else if (strcmp(upper, "WINDOW_STOP") == 0) { windowMode = false; logEvent("WINDOW_STOP", "0"); }
  else if (strncmp(upper, "TTLMS ", 6) == 0)  { ttlPulseMs = atol(upper + 6); logEvent("TTL_MS", String(ttlPulseMs).c_str()); }
  else if (strncmp(upper, "SYNCMS ", 7) == 0) { syncIntervalMs = atol(upper + 7); logEvent("SYNC_MS", String(syncIntervalMs).c_str()); }
  else if (strcmp(upper, "MDEBUG") == 0)      printMdebug();
  else if (strcmp(upper, "REGDUMP") == 0)     dumpRegisters();
  else if (strcmp(upper, "RESETMPR") == 0)    { mpr121Ready = initMpr121(); }
  else if (strncmp(upper, "THR ", 4) == 0) {
    char* sp = strchr(upper + 4, ' ');
    if (sp) {
      mprTouchThr = atoi(upper + 4);
      mprReleaseThr = atoi(sp + 1);
      mprWrite(0x41, mprTouchThr); mprWrite(0x42, mprReleaseThr);
      logEvent("THR", (String(mprTouchThr) + "," + String(mprReleaseThr)).c_str());
    }
  }
  else if (strncmp(upper, "DMIN ", 5) == 0)   { confirmDeltaMin = atoi(upper + 5); logEvent("DMIN", String(confirmDeltaMin).c_str()); }
  else                                         logEvent("ERR", "UNKNOWN_COMMAND");
}

// ── 诊断命令 ──

void printMdebug() {
  uint16_t f = mprRead16(0x04);
  uint16_t b = mprRead16(0x1E);
  uint8_t  t = mprRead8(0x00);
  int16_t diff = (int16_t)b - (int16_t)f;
  Serial.print(millis());
  Serial.print(F(",DEBUG,filtered=")); Serial.print(f);
  Serial.print(F(",baseline=")); Serial.print(b);
  Serial.print(F(",diff=")); Serial.print(diff);
  int16_t ad = (int16_t)b - (int16_t)f;
  if (ad < 0) ad = -ad;
  Serial.print(F(",touched=0x")); Serial.print(t, HEX);
  Serial.print(F(",thr=")); Serial.print(mprTouchThr);
  Serial.print(F(",dmin=")); Serial.println(ad >= confirmDeltaMin ? 1 : 0);
}

void dumpRegisters() {
  Serial.println(F("--- MPR121 register dump ---"));
  Serial.print(F("ECR(0x5E)=")); Serial.println(mprRead8(0x5E), HEX);
  Serial.print(F("CONF1(0x5C)=")); Serial.println(mprRead8(0x5C), HEX);
  Serial.print(F("CONF2(0x5D)=")); Serial.println(mprRead8(0x5D), HEX);
  Serial.print(F("TOUCH_STAT(0x00)=")); Serial.println(mprRead8(0x00), HEX);
  Serial.print(F("OOR_STAT(0x02)=")); Serial.println(mprRead8(0x02), HEX);
  Serial.print(F("E0_TOUCH_THR(0x41)=")); Serial.println(mprRead8(0x41));
  Serial.print(F("E0_REL_THR(0x42)=")); Serial.println(mprRead8(0x42));
  Serial.print(F("DEBOUNCE(0x5B)=")); Serial.println(mprRead8(0x5B), HEX);

  uint16_t f0 = mprRead16(0x04);
  uint16_t b0 = mprRead16(0x1E);
  Serial.print(F("E0 filtered=")); Serial.print(f0);
  Serial.print(F(" baseline=")); Serial.print(b0);
  Serial.print(F(" diff=")); Serial.println((int16_t)b0 - (int16_t)f0);

  // 读 CDC 原始计数（电极 0 的 CDC: 0x59-0x5A？）
  // 实际上是 0x04-0x05=filtered, 0x1E-0x1F=baseline
  Serial.println(F("--- end dump ---"));
}

// ═══════════════════════════════════════════════════
// 按钮
// ═══════════════════════════════════════════════════

void readButton() {
  static bool lastButton = HIGH;
  bool button = digitalRead(buttonPin);
  if (lastButton == HIGH && button == LOW) {
    startDose(doseMs);
  }
  lastButton = button;
}

// ═══════════════════════════════════════════════════
// 舔水检测
// ═══════════════════════════════════════════════════

void readLick(unsigned long now) {
  if (!mpr121Ready) return;

  // 降频：每 5ms 读一次（200Hz），防 I2C 总线风暴
  if (now - lastMprRead < 5) return;
  lastMprRead = now;

  // I2C 异常恢复
  if (!i2cOk) { i2cRecover(); return; }

  // 读 MPR121 寄存器（一次 3 字节批量读，减少 I2C 事务）
  uint8_t touchedReg = mprRead8(0x00);
  uint16_t filtered = mprRead16(0x04);
  uint16_t baseline = mprRead16(0x1E);
  if (!i2cOk) return;  // 本次读取失败则跳过

  bool hwTouched = touchedReg & 0x01;
  int16_t delta = (int16_t)baseline - (int16_t)filtered;
  int16_t adelta = delta < 0 ? -delta : delta;
  bool signalOk = adelta >= confirmDeltaMin;
  bool isTouched = hwTouched && signalOk;

  if (isTouched) confirmCnt++;
  else           confirmCnt = 0;
  bool confirmed = (confirmCnt >= 2);

  // 上升沿 → 触发舔水
  if (confirmed && !lastTouched && !lickLatched &&
      (now - lastLickAt >= lickRefractoryMs)) {
    lastLickAt = now;
    lickLatched = true;
    pulseLickTtl(now);
    logEvent("LICK", (String(lickElectrode)).c_str());
    if (windowMode && !windowRewarded) {
      startWindowReward(windowRewardMs);
      logEvent("WINDOW_LICK", (String(windowRewardMs)).c_str());
    }
  }

  // 释放检测
  if (!confirmed && lastTouched) lastReleaseAt = now;
  if (lickLatched && !confirmed && (now - lastReleaseAt >= lickReleaseMs))
    lickLatched = false;

  lastTouched = confirmed;
}

// ═══════════════════════════════════════════════════
// 给水
// ═══════════════════════════════════════════════════

void startDose(unsigned long ms) {
  if (ms == 0) return;
  unsigned long now = millis();
  autoMode = false;
  pumpRunning = true;
  pumpStopAt = now + ms;
  setPump(true);
  pulseRewardTtl(now);
  pulseCueTtl(now);
  logEvent("WATER", (String(ms)).c_str());
}

void startWindowReward(unsigned long ms) {
  if (ms == 0) return;
  unsigned long now = millis();
  windowRewarded = true;
  autoMode = false;
  pumpRunning = true;
  pumpStopAt = now + ms;
  setPump(true);
  pulseRewardTtl(now);
  logEvent("WINDOW_REWARD", (String(ms)).c_str());
}

// ═══════════════════════════════════════════════════
// 定时更新
// ═══════════════════════════════════════════════════

void updateWindow(unsigned long now) {
  if (!windowMode) return;
  if (!windowRewarded && timeReached(now, windowStartAt + windowDurationMs)) {
    windowMode = false; logEvent("WINDOW_END", "MISSED");
  }
  if (windowRewarded && !pumpRunning) {
    windowMode = false; logEvent("WINDOW_END", "REWARDED");
  }
}

void updatePump(unsigned long now) {
  if (pumpRunning && !autoMode && timeReached(now, pumpStopAt)) {
    pumpRunning = false; setPump(false); logEvent("WATER_END", "0");
  }
}

void updateSync(unsigned long now) {
  if (syncIntervalMs == 0) return;
  if (nextSyncAt == 0) nextSyncAt = now + syncIntervalMs;
  if (timeReached(now, nextSyncAt)) {
    digitalWrite(syncTtlPin, HIGH);
    syncTtlOffAt = now + ttlPulseMs;
    nextSyncAt += syncIntervalMs;
    // TTL 脉冲照发，但不打串口日志（减少刷屏）
  }
}

void updateTtls(unsigned long now) {
  if (rewardTtlOffAt && timeReached(now, rewardTtlOffAt)) { digitalWrite(rewardTtlPin, LOW); rewardTtlOffAt = 0; }
  if (lickTtlOffAt   && timeReached(now, lickTtlOffAt))   { digitalWrite(lickTtlPin, LOW);   lickTtlOffAt = 0; }
  if (syncTtlOffAt   && timeReached(now, syncTtlOffAt))   { digitalWrite(syncTtlPin, LOW);   syncTtlOffAt = 0; }
  if (cueTtlOffAt    && timeReached(now, cueTtlOffAt))    { digitalWrite(cueTtlPin, LOW);    cueTtlOffAt = 0; }
}

// ═══════════════════════════════════════════════════
// TTL 脉冲
// ═══════════════════════════════════════════════════

void pulseRewardTtl(unsigned long now) { digitalWrite(rewardTtlPin, HIGH); rewardTtlOffAt = now + ttlPulseMs; }
void pulseLickTtl(unsigned long now)   { digitalWrite(lickTtlPin, HIGH);   lickTtlOffAt   = now + ttlPulseMs; }
void pulseCueTtl(unsigned long now)    { digitalWrite(cueTtlPin, HIGH);    cueTtlOffAt    = now + ttlPulseMs; }

// ═══════════════════════════════════════════════════
// 泵 / LED
// ═══════════════════════════════════════════════════

void setPump(bool on) { digitalWrite(pumpPin, on ? HIGH : LOW); digitalWrite(ledPin, on ? HIGH : LOW); }

void setAllTtlsLow() {
  digitalWrite(rewardTtlPin, LOW); digitalWrite(lickTtlPin, LOW);
  digitalWrite(syncTtlPin, LOW);   digitalWrite(cueTtlPin, LOW);
}

// ═══════════════════════════════════════════════════
// 工具函数
// ═══════════════════════════════════════════════════

bool timeReached(unsigned long now, unsigned long target) { return (long)(now - target) >= 0; }

const char* statusText() {
  static char buf[80];
  snprintf(buf, sizeof(buf), "dose_ms=%lu,pump=%d,mpr121=%d,sync_ms=%lu",
           doseMs, digitalRead(pumpPin), mpr121Ready, syncIntervalMs);
  return buf;
}

void logEvent(const char* eventName, const char* value) {
  Serial.print(millis()); Serial.print(",");
  Serial.print(eventName); Serial.print(",");
  Serial.println(value);
}

void printHelp() {
  Serial.println(F("Commands: WATER [ms], DOSE ms, PUMP ON/OFF, STOP, TTLMS ms, SYNCMS ms,"));
  Serial.println(F("  CUE, WINDOW dur reward, WINDOW_STOP, MDEBUG, REGDUMP,"));
  Serial.println(F("  THR t r      (touch/release threshold, lower=more sensitive)"));
  Serial.println(F("  DMIN min     (software confirm delta, default 5)"));
  Serial.println(F("  RESETMPR     (re-init MPR121)"));
  Serial.println(F("  STATUS, HELP"));
}
