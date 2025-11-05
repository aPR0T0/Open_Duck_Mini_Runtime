import random
import numpy as np

# Default eye color (dark blue)
EYE_COLOR = np.array([25,25, 250])/255

class Expression:
    def __init__(self, eyes_rgb=(1.0, 1.0, 1.0), eyes_strength=1.0, sound=None):
        self.eyes_rgb = eyes_rgb
        self.eyes_strength = eyes_strength
        self.sound = sound


class BlinkingEyes:
    def __init__(self):
        # Frame counter for 50Hz operation
        self._frame_counter = 0
        
        # Blink state variables
        self._next_blink_frame = self._generate_next_blink_frame()
        self._blink_state = "normal"  # "normal", "blinking", "double_blink_pause"
        self._blink_frames_remaining = 0
        self._double_blink_pause_frames = 0
        
        # Current eye color
        self._current_color = EYE_COLOR
        
    def _generate_next_blink_frame(self):
        """Generate next blink time in frames (3-8 seconds at 50Hz)"""
        return self._frame_counter + random.randint(150, 400)  # 3-8 seconds * 50 fps

    def _generate_blink_duration_frames(self):
        """Generate blink duration in frames (0.08-0.12 seconds at 50Hz)"""
        return random.randint(4, 6)  # 0.08-0.12 seconds * 50 fps

    def _generate_double_blink_pause_frames(self):
        """Generate pause between double blinks in frames (0.08-0.15 seconds at 50Hz)"""
        return random.randint(4, 8)  # 0.08-0.15 seconds * 50 fps
        
    def update(self):
        """Update blinking state and return current eye color. Call at 50Hz."""
        if self._blink_state == "normal":
            # Eye stays on
            self._current_color = EYE_COLOR
            
            # Check if it's time to blink
            if self._frame_counter >= self._next_blink_frame:
                self._blink_state = "blinking"
                self._blink_frames_remaining = self._generate_blink_duration_frames()
                
        elif self._blink_state == "blinking":
            if self._blink_frames_remaining > 0:
                # Eye closed during blink
                self._current_color = (0, 0, 0)
                self._blink_frames_remaining -= 1
            else:
                # Blink finished, eye opens
                self._current_color = EYE_COLOR
                
                # 10% chance of double blink
                if random.random() < 0.1:
                    self._blink_state = "double_blink_pause"
                    self._double_blink_pause_frames = self._generate_double_blink_pause_frames()
                else:
                    self._blink_state = "normal"
                    self._next_blink_frame = self._generate_next_blink_frame()
                    
        elif self._blink_state == "double_blink_pause":
            # Eye stays on during pause
            self._current_color = EYE_COLOR
            
            if self._double_blink_pause_frames > 0:
                self._double_blink_pause_frames -= 1
            else:
                # Start second blink
                self._blink_state = "blinking"
                self._blink_frames_remaining = self._generate_blink_duration_frames()
                # After this blink, go back to normal
                self._next_blink_frame = self._generate_next_blink_frame()
        
        self._frame_counter += 1
        return Expression(self._current_color)
        
    def get_current_color(self):
        """Get current eye color without updating state"""
        return self._current_color

