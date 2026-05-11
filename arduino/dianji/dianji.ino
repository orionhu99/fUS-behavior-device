const int stepPin = 2;
const int dirPin  = 3;

int stepDelay = 2000;
bool stopFlag = false;

void setup() {
  pinMode(stepPin, OUTPUT);
  pinMode(dirPin, OUTPUT);

  Serial.begin(9600);
  Serial.println("Ready");
}

void loop() {

  // 随时检查串口
  if (Serial.available() > 0) {
    char cmd = Serial.read();

    if (cmd == 'F') {
      stopFlag = false;
      digitalWrite(dirPin, HIGH);
      Serial.println("Forward");
      moveSteps(1000); // 无限长运动，用S打断
    }

    else if (cmd == 'B') {
      stopFlag = false;
      digitalWrite(dirPin, LOW);
      Serial.println("Backward");
      moveSteps(1000);
    }

    else if (cmd == 'S') {
      stopFlag = true;
      Serial.println("STOP");
    }
  }
}

void moveSteps(long steps) {
  for (long i = 0; i < steps; i++) {

    if (Serial.available() > 0) {
      char cmd = Serial.read();
      if (cmd == 'S') {
        stopFlag = true;
      }
    }

    if (stopFlag) {
      Serial.println("Stopped");
      break;
    }

    digitalWrite(stepPin, HIGH);
    delayMicroseconds(stepDelay);
    digitalWrite(stepPin, LOW);
    delayMicroseconds(stepDelay);
  }
}