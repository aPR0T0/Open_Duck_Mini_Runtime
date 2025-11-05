import pigpio
import numpy as np
import time
import random
from threading import Thread

# RGB LED pins
RED_PIN = 19
GREEN_PIN = 26
BLUE_PIN = 13

# Default eye color (dark blue)
EYE_COLOR = np.array([8, 29, 54])/255


class Eyes:
    def __init__(self):
        # Initialize pigpio
        self.pi = pigpio.pi()
        if not self.pi.connected:
            raise RuntimeError("Could not connect to pigpio daemon. Run 'sudo pigpiod' first.")
        
        # PWM range for pigpio is 0-255
        self._pwm_range = 255
        
        Thread(target=self.run, daemon=True).start()

    def set_color(self, r, g, b):
        """Set LED color with floats 0.0–1.0"""
        # Convert 0-1 range to 0-255 for pigpio
        r_val = int(r * self._pwm_range)
        g_val = int(g * self._pwm_range)
        b_val = int(b * self._pwm_range)
        
        self.pi.set_PWM_dutycycle(RED_PIN, r_val)
        self.pi.set_PWM_dutycycle(GREEN_PIN, g_val)
        self.pi.set_PWM_dutycycle(BLUE_PIN, b_val)

    def blink(self, r=1.0, g=0.0, b=0.0):
        """Solid blink (no fade, just off/on)"""
        # Eye closes
        self.set_color(0, 0, 0)
        time.sleep(random.uniform(0.08, 0.12))  # blink duration
        # Eye opens
        self.set_color(r, g, b)

    def run(self):
        while True:
            # Eye stays on
            self.set_color(*EYE_COLOR)  # set to eye color
            
            # Wait random time before blink
            time.sleep(random.uniform(3, 8))

            # Normal blink
            self.blink(*EYE_COLOR)

            # ~10% chance of a quick second blink
            if random.random() < 0.1:
                time.sleep(random.uniform(0.08, 0.15))  # short pause
                self.blink(*EYE_COLOR)

    def cleanup(self):
        # Turn off all LEDs
        self.pi.set_PWM_dutycycle(RED_PIN, 0)
        self.pi.set_PWM_dutycycle(GREEN_PIN, 0)
        self.pi.set_PWM_dutycycle(BLUE_PIN, 0)
        
        # Stop connection to pigpio daemon
        self.pi.stop()


if __name__ == "__main__":
    e = Eyes()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        e.cleanup()
