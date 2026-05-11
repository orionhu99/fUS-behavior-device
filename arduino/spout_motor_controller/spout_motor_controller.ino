// Nano for the motor mounted on the manual Z-stage water-spout module.
// The Z-stage itself is adjusted manually; this motor only drives the mounted
// spout/module mechanism.
// Keeps the original pins from your working sketch.

const byte stepPin = 2;
const byte dirPin = 3;
const byte enablePin = 4;
const bool enableActiveLow = true;

unsigned int stepDelayUs = 2000;
long positionSteps = 0;
long targetSteps = 0;
bool movingToTarget = false;
int jogDirection = 0;
unsigned long lastStepAt = 0;

String line;

void setup() {
  pinMode(stepPin, OUTPUT);
  pinMode(dirPin, OUTPUT);
  pinMode(enablePin, OUTPUT);
  digitalWrite(stepPin, LOW);
  digitalWrite(dirPin, LOW);
  setEnabled(true);

  Serial.begin(115200);
  while (!Serial) {}
  Serial.println("READY,SPOUT_MOTOR");
  printHelp();
}

void loop() {
  readSerial();
  updateMotion();
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
    logEvent("STATUS", String(positionSteps));
  } else if (cmd == "ZERO") {
    positionSteps = 0;
    targetSteps = 0;
    movingToTarget = false;
    logEvent("ZERO", "0");
  } else if (cmd == "STOP" || cmd == "S") {
    jogDirection = 0;
    movingToTarget = false;
    logEvent("STOP", String(positionSteps));
  } else if (cmd == "ENABLE" || cmd == "EN") {
    setEnabled(true);
    logEvent("ENABLE", "1");
  } else if (cmd == "DISABLE" || cmd == "DIS") {
    setEnabled(false);
    logEvent("ENABLE", "0");
  } else if (cmd == "F") {
    startJog(1);
  } else if (cmd == "B") {
    startJog(-1);
  } else if (cmd.startsWith("JOG ")) {
    int dir = cmd.endsWith("B") ? -1 : 1;
    startJog(dir);
  } else if (cmd.startsWith("STEP ")) {
    long delta = parseLongAfterSpace(cmd, 0);
    targetSteps = positionSteps + delta;
    movingToTarget = true;
    jogDirection = 0;
    logEvent("STEP_TARGET", String(targetSteps));
  } else if (cmd.startsWith("GOTO ")) {
    targetSteps = parseLongAfterSpace(cmd, positionSteps);
    movingToTarget = true;
    jogDirection = 0;
    logEvent("GOTO_TARGET", String(targetSteps));
  } else if (cmd.startsWith("SPEED ")) {
    long value = parseLongAfterSpace(cmd, stepDelayUs);
    if (value >= 100 && value <= 20000) {
      stepDelayUs = (unsigned int)value;
      logEvent("SPEED_US", String(stepDelayUs));
    } else {
      logEvent("ERR", "SPEED_RANGE_100_20000");
    }
  } else {
    logEvent("ERR", "UNKNOWN_COMMAND");
  }
}

void updateMotion() {
  int dir = 0;
  if (jogDirection != 0) {
    dir = jogDirection;
  } else if (movingToTarget) {
    if (targetSteps == positionSteps) {
      movingToTarget = false;
      logEvent("MOVE_DONE", String(positionSteps));
      return;
    }
    dir = targetSteps > positionSteps ? 1 : -1;
  } else {
    return;
  }

  unsigned long now = micros();
  if (now - lastStepAt >= (unsigned long)stepDelayUs * 2) {
    stepOnce(dir);
    lastStepAt = now;
  }
}

void stepOnce(int dir) {
  digitalWrite(dirPin, dir > 0 ? HIGH : LOW);
  digitalWrite(stepPin, HIGH);
  delayMicroseconds(stepDelayUs);
  digitalWrite(stepPin, LOW);
  positionSteps += dir > 0 ? 1 : -1;
}

void startJog(int dir) {
  setEnabled(true);
  jogDirection = dir;
  movingToTarget = false;
  logEvent("JOG", dir > 0 ? "F" : "B");
}

void setEnabled(bool enabled) {
  if (enableActiveLow) {
    digitalWrite(enablePin, enabled ? LOW : HIGH);
  } else {
    digitalWrite(enablePin, enabled ? HIGH : LOW);
  }
}

long parseLongAfterSpace(String cmd, long fallback) {
  int idx = cmd.indexOf(' ');
  if (idx < 0) return fallback;
  return cmd.substring(idx + 1).toInt();
}

void logEvent(String eventName, String value) {
  Serial.print(millis());
  Serial.print(",");
  Serial.print(eventName);
  Serial.print(",");
  Serial.println(value);
}

void printHelp() {
  Serial.println("Commands: STEP signed_steps, GOTO pos, F, B, JOG F, JOG B, STOP, ENABLE, DISABLE, SPEED us, ZERO, STATUS, HELP");
  Serial.println("CSV events: arduino_ms,event,value");
}
