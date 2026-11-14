"""
kiosk_controller.py
Controller for the Satisfaction Kiosk (Mini-Lab 3)
Built on the PicoLibrary StateModel (same structure as ModelTemplate.py).

States
  0 IDLE       - waiting for a visitor, lights off, LCD shows stats
  1 PROMPT     - "Rate your visit!", green/red buttons active, 5 s timeout
  2 THANK_YOU  - thank-you message + satisfaction meter for 3 s
  3 ALARM      - satisfaction < 30%: red lights + siren until the manager acts

Transitions
  IDLE      --sonar_trip-------------> PROMPT
  PROMPT    --green_press / red_press-> THANK_YOU   (vote counted on entry)
  PROMPT    --timer_timeout----------> IDLE        (nobody pressed)
  THANK_YOU --feedback_ok------------> IDLE        [satisfaction >= 30%]
  THANK_YOU --feedback_low-----------> ALARM       [satisfaction < 30%]
  ALARM     --manager_press----------> IDLE        (alarm silenced)
  ALARM     --green_press------------> IDLE        (statistics reset)
"""
import time
from Log import *
from StateModel import *
from Counters import *
from Button import *
from Lights import *
from LightStrip import LightStrip
from Buzzer import PassiveBuzzer
from Displays import LCDDisplay
from Sensors import Sensor
from machine import Pin
from kiosk_model import FeedbackStats

# ---- pin map (matches the Wokwi diagram) ----
LCD_SDA, LCD_SCL = 0, 1
GREEN_PIN, RED_PIN, MANAGER_PIN = 16, 17, 18
TRIG_PIN, ECHO_PIN = 2, 3
BUZZER_PIN = 15
STRIP_PIN = 22
NUM_LEDS = 8

# ---- states ----
IDLE, PROMPT, THANK_YOU, ALARM = 0, 1, 2, 3

PROMPT_SECONDS = 5
THANK_YOU_MS = 3000


class VisitorSensor(Sensor):
    """HC-SR04 ultrasonic sensor built on the PicoLibrary Sensor base class.
    Tripped when a visitor is closer than the threshold (10 cm).
    A missing echo (-1) is ignored so it is not mistaken for a visitor."""

    def __init__(self, *, trigger, echo, name="sonar", threshold=10.0):
        super().__init__(name, True)
        self._trigger = Pin(trigger, Pin.OUT)
        self._echo = Pin(echo, Pin.IN)
        self._threshold = threshold

    def distance(self) -> float:
        self._trigger.off()
        time.sleep_us(2)
        self._trigger.on()
        time.sleep_us(10)
        self._trigger.off()
        start = time.ticks_us()
        while self._echo.value() == 0:
            if time.ticks_diff(time.ticks_us(), start) > 30000:
                return -1
        t0 = time.ticks_us()
        while self._echo.value() == 1:
            if time.ticks_diff(time.ticks_us(), t0) > 30000:
                return -1
        return time.ticks_diff(time.ticks_us(), t0) * 0.0343 / 2

    def rawValue(self):
        return self.distance()

    def tripped(self) -> bool:
        d = self.distance()
        return 0 < d < self._threshold


class KioskController:

    def __init__(self):
        # model (pure logic)
        self._stats = FeedbackStats(threshold=30, min_votes=5)

        # views / hardware (PicoLibrary)
        self._display = LCDDisplay(sda=LCD_SDA, scl=LCD_SCL)
        self._strip = LightStrip(pin=STRIP_PIN, numleds=NUM_LEDS, brightness=0.5)
        self._buzzer = PassiveBuzzer(BUZZER_PIN)

        # state model with 4 states, this controller is the handler
        self._model = StateModel(4, self, debug=True)

        self._green = Button(GREEN_PIN, "green", handler=None)
        self._red = Button(RED_PIN, "red", handler=None)
        self._manager = Button(MANAGER_PIN, "manager", handler=None)
        self._model.addButton(self._green)
        self._model.addButton(self._red)
        self._model.addButton(self._manager)

        self._sonar = VisitorSensor(trigger=TRIG_PIN, echo=ECHO_PIN, name="sonar", threshold=10.0)
        self._model.addSensor(self._sonar)

        self._timer = SoftwareTimer(name="timer", handler=None)
        self._model.addTimer(self._timer)

        self._model.addCustomEvent("feedback_ok")
        self._model.addCustomEvent("feedback_low")

        self._model.addTransition(IDLE, ["sonar_trip"], PROMPT)
        self._model.addTransition(PROMPT, ["green_press", "red_press"], THANK_YOU)
        self._model.addTransition(PROMPT, ["timer_timeout"], IDLE)
        self._model.addTransition(THANK_YOU, ["feedback_ok"], IDLE)
        self._model.addTransition(THANK_YOU, ["feedback_low"], ALARM)
        self._model.addTransition(ALARM, ["manager_press", "green_press"], IDLE)

        self._entered_at = time.ticks_ms()
        self._pending = None
        self._tone = None

    # ---------- helpers ----------
    def _show(self, line1, line2=""):
        """Queue text for the LCD. The actual write happens in stateDo()
        (main loop), because entry actions can run inside a button
        interrupt while the LCD is busy."""
        self._pending = ((line1 + " " * 16)[:16], (line2 + " " * 16)[:16])

    def _flush_display(self):
        if self._pending:
            line1, line2 = self._pending
            self._pending = None
            self._display.showText(line1, 0, 0)
            self._display.showText(line2, 1, 0)

    def _show_meter(self):
        """Innovation: light strip as a satisfaction meter (red -> green)."""
        pct = self._stats.satisfaction()
        lit = max(1, round(NUM_LEDS * pct / 100))
        color = (int(255 * (100 - pct) / 100), int(255 * pct / 100), 0)
        self._strip.setColor(color, lit)

    def _elapsed(self):
        return time.ticks_diff(time.ticks_ms(), self._entered_at)

    # ---------- StateModel handler methods ----------
    def stateEntered(self, state, event):
        Log.d(f"State {state} entered on event {event}")
        self._entered_at = time.ticks_ms()

        if state == IDLE:
            if event == "green_press":          # came from ALARM with the reset button
                self._stats.reset()
                Log.i("Statistics reset")
            self._strip.off()
            self._show("Feedback Kiosk", str(self._stats))

        elif state == PROMPT:
            self._strip.setColor(WHITE)
            self._show("Rate your visit!", "Green=:) Red=:(")
            self._timer.start(PROMPT_SECONDS)

        elif state == THANK_YOU:
            if event == "green_press":
                self._stats.add_positive()
                self._show("Thank you! :)", f"Happy: {self._stats.satisfaction()}%")
            else:
                self._stats.add_negative()
                self._show("Sorry! We'll fix", f"Happy: {self._stats.satisfaction()}%")
            self._show_meter()

        elif state == ALARM:
            self._strip.setColor(RED)
            self._show("!! LOW SCORE !!", f"Happy: {self._stats.satisfaction()}%")

    def stateLeft(self, state, event):
        Log.d(f"State {state} exited on event {event}")
        if state == PROMPT:
            self._timer.cancel()
        elif state == ALARM:
            self._buzzer.stop()
            self._tone = None
            if event == "manager_press":
                Log.i("Alarm silenced by manager")

    def stateEvent(self, state, event) -> bool:
        return False

    def stateDo(self, state):
        self._flush_display()
        if state == THANK_YOU:
            if self._elapsed() > THANK_YOU_MS:
                if self._stats.is_below_threshold():
                    self._model.processEvent("feedback_low")
                else:
                    self._model.processEvent("feedback_ok")
        elif state == ALARM:
            # siren: alternate two tones every half second
            tone = 1000 if (self._elapsed() // 500) % 2 == 0 else 700
            if tone != self._tone:
                self._buzzer.play(tone)
                self._tone = tone

    def run(self):
        self._model.run()

    def stop(self):
        self._model.stop()


if __name__ == "__main__":
    k = KioskController()
    try:
        k.run()
    except KeyboardInterrupt:
        k.stop()
