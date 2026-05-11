const int buttonPin = 2;
const int ledPin = 3;
const int pumpPin = 5;

// ===== 参数 =====
const unsigned long doseTime = 400;
const unsigned long longPressTime = 1500;
const unsigned long blinkInterval = 150;

// ===== 状态 =====
bool lastButtonState = HIGH;
bool buttonState = HIGH;

bool pumpRunning = false;
bool autoMode = false;
bool longPressTriggered = false;
bool ignoreRelease = false;   // ⭐关键新增

unsigned long pressStartTime = 0;
unsigned long pumpStartTime = 0;
unsigned long lastBlinkTime = 0;
bool ledState = false;

void setup() {
  pinMode(buttonPin, INPUT_PULLUP);
  pinMode(ledPin, OUTPUT);
  pinMode(pumpPin, OUTPUT);

  digitalWrite(ledPin, LOW);
  digitalWrite(pumpPin, LOW);
}

void loop() {
  buttonState = digitalRead(buttonPin);

  // ===== 按下瞬间（下降沿）=====
  if (lastButtonState == HIGH && buttonState == LOW) {

    if (autoMode) {
      // 退出AUTO
      autoMode = false;
      stopPump();
      ignoreRelease = true;  // ⭐忽略接下来的松开
    } 
    else {
      pressStartTime = millis();
      longPressTriggered = false;
    }
  }

  // ===== 按住过程中检测长按 =====
  if (buttonState == LOW && !autoMode && !longPressTriggered) {
    if (millis() - pressStartTime >= longPressTime) {
      autoMode = true;
      longPressTriggered = true;
      startPump(); // 立即启动
    }
  }

  // ===== 松开瞬间（上升沿）=====
  if (lastButtonState == LOW && buttonState == HIGH) {

    if (ignoreRelease) {
      // ⭐这次松开是用来退出AUTO的，不做任何操作
      ignoreRelease = false;
    }
    else if (!autoMode && !longPressTriggered) {
      // 正常短按
      startDose();
    }
  }

  lastButtonState = buttonState;

  // ===== 单次模式计时 =====
  if (pumpRunning && !autoMode) {
    if (millis() - pumpStartTime >= doseTime) {
      stopPump();
    }
  }

  // ===== AUTO模式：持续出水 + LED闪烁 =====
  if (autoMode) {
    digitalWrite(pumpPin, HIGH);

    if (millis() - lastBlinkTime >= blinkInterval) {
      lastBlinkTime = millis();
      ledState = !ledState;
      digitalWrite(ledPin, ledState);
    }
  }
}

// ===== 功能函数 =====

void startDose() {
  pumpRunning = true;
  pumpStartTime = millis();
  startPump();
}

void startPump() {
  digitalWrite(pumpPin, HIGH);
  digitalWrite(ledPin, HIGH);
}

void stopPump() {
  pumpRunning = false;
  digitalWrite(pumpPin, LOW);
  digitalWrite(ledPin, LOW);
}