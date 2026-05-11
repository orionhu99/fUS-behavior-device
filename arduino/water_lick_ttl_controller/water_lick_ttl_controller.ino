#include <Wire.h>
#include "Adafruit_MPR121.h"

// Nano for water delivery, lick detection, and TTL event outputs.
// Requires the Adafruit MPR121 library in Arduino IDE.

const byte buttonPin = 2;
const byte ledPin = 3;
const byte pumpPin = 5;

const byte rewardTtlPin = 8;
const byte lickTtlPin = 9;
const byte syncTtlPin = 10;
const byte cueTtlPin = 11;     // Connect to Bpod input that triggers HiFi 8 kHz cue.

const byte lickElectrode = 0;

unsigned long doseMs = 400;
unsigned long ttlPulseMs = 10;
unsigned long lickRefractoryMs = 40;
unsigned long syncIntervalMs = 1000;

bool pumpRunning = false;
bool autoMode = false;
bool mpr121Ready = false;
bool lastTouched = false;

// 窗口模式：cue 触发后进入自治舔水检测窗
bool windowMode = false;
unsigned long windowStartAt = 0;
unsigned long windowDurationMs = 0;
unsigned long windowRewardMs = 0;
bool windowRewarded = false;

unsigned long pumpStopAt = 0;
unsigned long lastLickAt = 0;
unsigned long nextSyncAt = 0;

unsigned long rewardTtlOffAt = 0;
unsigned long lickTtlOffAt = 0;
unsigned long syncTtlOffAt = 0;
unsigned long cueTtlOffAt = 0;

String line;
Adafruit_MPR121 cap = Adafruit_MPR121();

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

  // 先试 0x5A（标准），失败则试 0x5B（国产模块常见地址）
  mpr121Ready = cap.begin(0x5A);
  if (!mpr121Ready) {
    mpr121Ready = cap.begin(0x5B);
    if (mpr121Ready) {
      Serial.println("MPR121 found at 0x5B (alt address)");
    }
  }
  if (mpr121Ready) {
    cap.setThresholds(16, 8);
  }

  logEvent("READY", mpr121Ready ? "MPR121_OK" : "MPR121_MISSING");
  printHelp();
}

void loop() {
  const unsigned long now = millis();
  readSerial();
  readButton();
  readLick(now);
  updatePump(now);
  updateTtls(now);
  updateSync(now);
  updateWindow(now);
}

void readSerial() {
  while (Serial.available() > 0) {
    char c = (char)Serial.read();
    if (c == '\n' || c == '\r') {
      if (line.length() > 0) {
        handleCommand(line);
        line = "";
      }
    } else {
      line += c;
      if (line.length() > 80) line = "";
    }
  }
}

void handleCommand(String cmd) {
  cmd.trim();
  cmd.toUpperCase();

  if (cmd == "HELP") {
    printHelp();
  } else if (cmd == "STATUS") {
    logEvent("STATUS", statusText());
  } else if (cmd == "WATER") {
    startDose(doseMs);
  } else if (cmd.startsWith("WATER ")) {
    startDose(parseNumberAfterSpace(cmd, doseMs));
  } else if (cmd.startsWith("DOSE ")) {
    doseMs = parseNumberAfterSpace(cmd, doseMs);
    logEvent("DOSE_MS", String(doseMs));
  } else if (cmd == "PUMP ON") {
    autoMode = true;
    setPump(true);
    logEvent("PUMP", "ON");
  } else if (cmd == "PUMP OFF" || cmd == "STOP") {
    autoMode = false;
    pumpRunning = false;
    windowMode = false;
    setPump(false);
    logEvent("PUMP", "OFF");
  } else if (cmd == "CUE") {
    pulseCueTtl(millis());
    logEvent("CUE", "1");
  } else if (cmd.startsWith("WINDOW ")) {
    int idx = cmd.indexOf(' ');
    int idx2 = cmd.indexOf(' ', idx + 1);
    if (idx2 > 0) {
      windowDurationMs = cmd.substring(idx + 1, idx2).toInt();
      windowRewardMs = cmd.substring(idx2 + 1).toInt();
      windowMode = true;
      windowStartAt = millis();
      windowRewarded = false;
      logEvent("WINDOW_START", String(windowDurationMs) + "," + String(windowRewardMs));
    }
  } else if (cmd == "WINDOW_STOP") {
    windowMode = false;
    logEvent("WINDOW_STOP", "0");
  } else if (cmd.startsWith("TTLMS ")) {
    ttlPulseMs = parseNumberAfterSpace(cmd, ttlPulseMs);
    logEvent("TTL_MS", String(ttlPulseMs));
  } else if (cmd.startsWith("SYNCMS ")) {
    syncIntervalMs = parseNumberAfterSpace(cmd, syncIntervalMs);
    logEvent("SYNC_MS", String(syncIntervalMs));
  } else if (cmd == "MDEBUG") {
    // 打印 MPR121 原始寄存器用于诊断
    uint16_t touched = cap.touched();
    int filtered0 = cap.filteredData(lickElectrode);
    int baseline0 = cap.baselineData(lickElectrode);
    Serial.print(millis()); Serial.print(",DEBUG,");
    Serial.print("touched=0x"); Serial.print(touched, HEX);
    Serial.print(",filtered="); Serial.print(filtered0);
    Serial.print(",baseline="); Serial.println(baseline0);
  } else {
    logEvent("ERR", "UNKNOWN_COMMAND");
  }
}

void readButton() {
  static bool lastButton = HIGH;
  bool button = digitalRead(buttonPin);
  if (lastButton == HIGH && button == LOW) {
    startDose(doseMs);
  }
  lastButton = button;
}

void readLick(unsigned long now) {
  if (!mpr121Ready) return;

  // 软件舔水检测：用 filtered 变化代替硬件 touched 位
  int filtered = cap.filteredData(lickElectrode);
  if (filtered < 0) filtered = 0;

  // 指数移动平均基线
  static float swBaseline = -1;
  if (swBaseline < 0) swBaseline = (float)filtered;
  swBaseline = swBaseline * 0.995 + filtered * 0.005;

  // 触碰使 filtered 下降（电容被人体泄放）
  int delta = (int)(swBaseline - filtered);
  bool isTouched = (delta >= 6);   // 变化 ≥4 视为舔水

  if (isTouched && !lastTouched && now - lastLickAt >= lickRefractoryMs) {
    lastLickAt = now;
    pulseLickTtl(now);
    logEvent("LICK", String(lickElectrode));
    if (windowMode && !windowRewarded) {
      startWindowReward(windowRewardMs);
      logEvent("WINDOW_LICK", String(windowRewardMs));
    }
  }
  lastTouched = isTouched;
}

void startDose(unsigned long ms) {
  if (ms == 0) return;
  unsigned long now = millis();
  autoMode = false;
  pumpRunning = true;
  pumpStopAt = now + ms;
  setPump(true);
  pulseRewardTtl(now);
  pulseCueTtl(now);
  logEvent("WATER", String(ms));
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
  logEvent("WINDOW_REWARD", String(ms));
}

void updateWindow(unsigned long now) {
  if (!windowMode) return;
  if (!windowRewarded && timeReached(now, windowStartAt + windowDurationMs)) {
    windowMode = false;
    logEvent("WINDOW_END", "MISSED");
  }
  if (windowRewarded && !pumpRunning) {
    windowMode = false;
    logEvent("WINDOW_END", "REWARDED");
  }
}

void updatePump(unsigned long now) {
  if (pumpRunning && !autoMode && timeReached(now, pumpStopAt)) {
    pumpRunning = false;
    setPump(false);
    logEvent("WATER_END", "0");
  }
}

void updateSync(unsigned long now) {
  if (syncIntervalMs == 0) return;
  if (nextSyncAt == 0) nextSyncAt = now + syncIntervalMs;
  if (timeReached(now, nextSyncAt)) {
    digitalWrite(syncTtlPin, HIGH);
    syncTtlOffAt = now + ttlPulseMs;
    nextSyncAt += syncIntervalMs;
    logEvent("SYNC", "1");
  }
}

void updateTtls(unsigned long now) {
  if (rewardTtlOffAt && timeReached(now, rewardTtlOffAt)) {
    digitalWrite(rewardTtlPin, LOW);
    rewardTtlOffAt = 0;
  }
  if (lickTtlOffAt && timeReached(now, lickTtlOffAt)) {
    digitalWrite(lickTtlPin, LOW);
    lickTtlOffAt = 0;
  }
  if (syncTtlOffAt && timeReached(now, syncTtlOffAt)) {
    digitalWrite(syncTtlPin, LOW);
    syncTtlOffAt = 0;
  }
  if (cueTtlOffAt && timeReached(now, cueTtlOffAt)) {
    digitalWrite(cueTtlPin, LOW);
    cueTtlOffAt = 0;
  }
}

void pulseRewardTtl(unsigned long now) {
  digitalWrite(rewardTtlPin, HIGH);
  rewardTtlOffAt = now + ttlPulseMs;
}

void pulseLickTtl(unsigned long now) {
  digitalWrite(lickTtlPin, HIGH);
  lickTtlOffAt = now + ttlPulseMs;
}

void pulseCueTtl(unsigned long now) {
  digitalWrite(cueTtlPin, HIGH);
  cueTtlOffAt = now + ttlPulseMs;
}

void setPump(bool on) {
  digitalWrite(pumpPin, on ? HIGH : LOW);
  digitalWrite(ledPin, on ? HIGH : LOW);
}

void setAllTtlsLow() {
  digitalWrite(rewardTtlPin, LOW);
  digitalWrite(lickTtlPin, LOW);
  digitalWrite(syncTtlPin, LOW);
  digitalWrite(cueTtlPin, LOW);
}

unsigned long parseNumberAfterSpace(String cmd, unsigned long fallback) {
  int idx = cmd.indexOf(' ');
  if (idx < 0) return fallback;
  long value = cmd.substring(idx + 1).toInt();
  if (value < 0) return fallback;
  return (unsigned long)value;
}

bool timeReached(unsigned long now, unsigned long target) {
  return (long)(now - target) >= 0;
}

String statusText() {
  String s = "dose_ms=" + String(doseMs);
  s += ",pump=" + String(digitalRead(pumpPin));
  s += ",mpr121=" + String(mpr121Ready);
  s += ",sync_ms=" + String(syncIntervalMs);
  return s;
}

void logEvent(String eventName, String value) {
  Serial.print(millis());
  Serial.print(",");
  Serial.print(eventName);
  Serial.print(",");
  Serial.println(value);
}

void printHelp() {
  Serial.println("Commands: WATER [ms], DOSE ms, PUMP ON/OFF, STOP, TTLMS ms, SYNCMS ms, CUE, WINDOW dur_ms reward_ms, WINDOW_STOP, STATUS, HELP");
  Serial.println("CSV events: arduino_ms,event,value");
}
