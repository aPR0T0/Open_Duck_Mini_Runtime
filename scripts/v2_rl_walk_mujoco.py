import os
import time
import numpy as np
import threading

from mini_bdx_runtime.rustypot_position_hwi import HWI
from mini_bdx_runtime.raw_imu import Imu
from mini_bdx_runtime.xbox_controller import XBoxController
from mini_bdx_runtime.feet_contacts import FeetContacts
from mini_bdx_runtime.common.utils import LowPassActionFilter
from mini_bdx_runtime.eyes import Eyes
#from mini_bdx_runtime.sounds import Sounds
#from mini_bdx_runtime.antennas import Antennas
#from mini_bdx_runtime.projector import Projector
from mini_bdx_runtime.common import mini2_constants, dino_constants
from mini_bdx_runtime.common.policies import JoystickPolicy, StandingPolicy, EpisodicPolicy
from mini_bdx_runtime.common.modifiers_test import JoystickPolicyModifier, StandingPolicyModifier, EpisodicPolicyModifier
from mini_bdx_runtime.common.head_teleop_client import HeadTelop

class RLWalk:
    def __init__(
        self,
        serial_port: str = "/dev/ttyACM0",
        control_freq: float = 50,
        pid=[20, 0, 0],
        robot="dino",
        initial_policy_type="standing",
        cutoff_freq=50.0,
        teleop_host="10.144.135.208",
    ):

        # Control
        self.control_freq = control_freq
        self.pid = pid
        self.constants = eval(f"{robot}_constants")

        # Expression package
        #self.sounds = Sounds(volume=1.0, sound_directory="../mini_bdx_runtime/assets/")
        #self.antennas = Antennas()
        self.eyes = Eyes()
        #self.projector = Projector()

        self.head_teleop_client = HeadTelop(teleop_host)
        self.head_teleop_client.start()

        self.hwi = HWI(serial_port)
        self.imu = Imu(sampling_freq=int(self.control_freq),)
        self.feet_contacts = FeetContacts()

        # get current script path
        DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "../mini_bdx_runtime/data")

        # Define hardcoded paths for models
        self.model_paths = {
            "episodic": f"{DATA_PATH}/{robot}/models/{robot}_checkpoint_episodic_happy_dance.onnx",
            "joystick": f"{DATA_PATH}/{robot}/models/{robot}_checkpoint_joystick.onnx",
            "standing": f"{DATA_PATH}/{robot}/models/{robot}_checkpoint_standing.onnx",
        }
        
        self.reference_paths = {
            "episodic": f"{DATA_PATH}/{robot}/happy_dance.json",
        }
       
        # Initialize all policies 
        print("Loading all policies...")
        self.policies = {
            "joystick": JoystickPolicy(self.constants, self.model_paths["joystick"]),
            "standing": StandingPolicy(self.constants, self.model_paths["standing"]),
            "episodic": EpisodicPolicy(self.constants, self.model_paths["episodic"], self.reference_paths["episodic"])
        }

        # Initialize policy modifiers
        self.policy_modifiers = {
            "joystick": JoystickPolicyModifier(self.constants),
            "standing": StandingPolicyModifier(self.constants),
            "episodic": EpisodicPolicyModifier(self.constants)
        }
        
        # Set initial active policy
        self.active_policy_type = initial_policy_type
        self.policy = self.policies[self.active_policy_type]
        self.policy_modifier = self.policy_modifiers[self.active_policy_type]
        print(f"Initial active policy: {self.active_policy_type}")

        self.action_filter = LowPassActionFilter(50, cutoff_frequency=cutoff_freq)
        
        # Policy switching variables
        self.switch_pending = False
        self.target_policy_type = None
        self.switch_start_time = 0
        self.original_commands = None
        
        # Set decimation for all policies (how often to update)
        self.decimation = 1  # Default to 1 for real robot (no need for decimation)
        for policy in self.policies.values():
            if hasattr(policy, "decimation"):
                policy.decimation = self.decimation

        # Initialize commands
        self.commands = self.policy.get_default_commands()

        self.xbox_controller = XBoxController()
        self.use_controller = False
        # Start controller initialization in a separate thread
        self.controller_thread = threading.Thread(target=self.init_controller_thread)
        self.controller_thread.daemon = True  # Thread will exit when main program exits
        self.controller_thread.start()

        # Flag to track if legs are safe to control
        self.legs_enabled = False
        
        # Define joint groups once
        self.head_neck_tail_joints = ["neck_pitch", "head_pitch", "head_yaw", "tail"]
        self.leg_joints = [joint for joint in self.constants.JOINTS_ORDER 
                          if joint not in self.head_neck_tail_joints]
        
        # Store joint IDs once
        self.head_neck_tail_ids = [self.hwi.joints[joint] for joint in self.head_neck_tail_joints]
        self.leg_joint_ids = [self.hwi.joints[joint] for joint in self.leg_joints]
        
        # Initialize motors without enabling torque for legs
        self.start()

    def init_controller_thread(self):
        """Initialize Xbox controller in a separate thread"""
        if self.xbox_controller.wait_for_connection(timeout=None):
            print("Bluetooth controller connected successfully")
            self.use_controller = True
        else:
            print("Warning: Could not connect to Bluetooth controller")
            self.use_controller = False

    def request_policy_switch(self, new_policy_type):
        """Request a policy switch with specific requirements for each policy"""
        if new_policy_type == self.active_policy_type or self.switch_pending:
            return
            
        print(f"Requesting switch from {self.active_policy_type} to {new_policy_type} policy")
        self.target_policy_type = new_policy_type
        self.switch_pending = True
        
        # Handle standing policy switch specially - need to set commands to 0 and wait
        if self.active_policy_type == "standing":
            print("Standing policy: setting commands to 0 and waiting 0.5s")
            self.original_commands = self.commands.copy()
            self.commands = np.zeros_like(self.commands)
            self.switch_start_time = time.time()
        
    def check_switch_conditions(self):
        """Check if conditions are met to complete the policy switch"""
        if not self.switch_pending:
            return
            
        # For standing policy, we just need to wait 0.5 seconds
        if self.active_policy_type == "standing":
            if time.time() - self.switch_start_time >= 0.5:
                self.complete_policy_switch()
                return
                
        # For joystick policy, we need to check if phase is at 0
        elif self.active_policy_type == "joystick":
            if self.policy.imitation_i == 0:  # Allow small tolerance
                self.complete_policy_switch()
                return
                
        # For episodic policy, we need to check if imitation_i is at 0
        elif self.active_policy_type == "episodic":
            if self.policy.imitation_i == 0:  # Allow small tolerance
                self.complete_policy_switch()
                return
       
    def complete_policy_switch(self):
        """Complete the policy switch once conditions are met"""
        print(f"Switching from {self.active_policy_type} to {self.target_policy_type} policy")
        self.active_policy_type = self.target_policy_type
        self.policy = self.policies[self.target_policy_type]
        self.policy_modifier = self.policy_modifiers[self.target_policy_type]
        self.policy.reset()
        self.commands = self.policy.get_default_commands()
        
        # Reset switching state
        self.switch_pending = False
        self.target_policy_type = None
        self.switch_start_time = 0
        self.original_commands = None

    def get_sensors(self):
        joint_angles = self.hwi.get_present_positions()
        joint_vel = self.hwi.get_present_velocities()  # rad/s
        imu_data = self.imu.get_data()
        accelerometer = imu_data["accel"]
        gyro = imu_data["gyro"]
        
        # If legs are not enabled yet, simulate ground contacts for stability
        if not self.legs_enabled:
            contacts = [True, True]  # Both feet in contact with ground
        else:
            contacts = self.feet_contacts.get()

        return joint_angles, joint_vel, accelerometer, gyro, contacts
    
    def process_controller_input(self):
        """Process controller input to update commands"""
        if not self.use_controller or self.switch_pending:
            return
            
        # Check if controller is initialized before trying to use it
        try:
            # Get controller stick values
            stick_vals = self.xbox_controller.get_sticks()
            buttons = self.xbox_controller.get_buttons()
            
            # Check for policy switch buttons
            if buttons[0]: 
                self.request_policy_switch("joystick")
            elif buttons[1]: 
                self.request_policy_switch("standing")
            elif buttons[2]:  
                self.request_policy_switch("episodic")
                
            self.commands = self.policy.joystick_to_commands(stick_vals)
        except Exception as e:
            # Handle any exceptions that might occur if controller isn't fully ready
            pass

    def start(self):
        """Initialize motors by enabling only head, neck, and tail joints"""
        # Set kp=1 for head/neck/tail joints only
        head_neck_tail_kps = [20] * len(self.head_neck_tail_ids)
        
        # Set kps for head/neck/tail joints only (with kp=1)
        self.hwi.disable_torque(self.leg_joint_ids)
        self.hwi.set_kps(head_neck_tail_kps, self.head_neck_tail_ids)
        self.hwi.disable_torque(self.leg_joint_ids)
        
        print("Motors partially activated: head, neck and tail joints enabled at low torque")
        
        # Start a background thread to wait for safe position and enable leg joints
        self.safe_position_thread = threading.Thread(target=self.enable_legs_when_safe)
        self.safe_position_thread.daemon = True
        self.safe_position_thread.start()
    
    def enable_legs_when_safe(self):
        """Background thread to wait for safe leg position and then enable leg motors"""
        self.wait_for_safe_position()
        
        # Set kp values for leg joints
        leg_kps = [self.pid[0]] * len(self.leg_joint_ids)
        
        # Apply kps to leg joints
        self.hwi.set_kps(leg_kps, self.leg_joint_ids)
        
        # Set the flag to indicate legs are now enabled
        self.legs_enabled = True
        
        print("Hip pitch joints in safe position. Leg motors activated at normal torque.")

    def wait_for_safe_position(self, threshold_deg=20, check_interval=0.1):
        """Wait until hip pitch joints are within threshold of default position"""
        threshold_rad = np.deg2rad(threshold_deg)
        
        # Get indices of hip pitch joints
        right_hip_pitch_idx = self.constants.JOINTS_ORDER.index("right_hip_pitch")
        left_hip_pitch_idx = self.constants.JOINTS_ORDER.index("left_hip_pitch")
        
        print("Waiting for hip pitch joints to reach safe position...")
        while True:
            # Get current positions
            current_positions = self.hwi.get_present_positions()
            
            # Check if hip pitch joints are close to default (0 radians)
            right_hip_ok = abs(current_positions[right_hip_pitch_idx]) < threshold_rad
            left_hip_ok = abs(current_positions[left_hip_pitch_idx]) < threshold_rad
            
            if right_hip_ok and left_hip_ok:
                return
            
            time.sleep(check_interval)

    def run(self):
        i = 0
        try:
            while True:
                t = time.time()
    
                # Process controller input
                self.process_controller_input()
                
                # Check if we need to complete a policy switch
                if self.switch_pending:
                    self.check_switch_conditions()
                
                # Get sensor data
                joint_angles, joint_vel, accelerometer, gyro, contacts = self.get_sensors()
                
                # Use the policy to get motor commands
                motor_targets = self.policy.infer(
                    joint_angles, 
                    joint_vel, 
                    accelerometer, 
                    gyro, 
                    contacts,
                    self.commands
                )

                # Apply policy modifier with all the same parameters
                motor_targets = self.policy_modifier.modify(
                    motor_targets,
                    joint_pos=joint_angles,
                    joint_vel=joint_vel,
                    accel=accelerometer,
                    gyro=gyro,
                    contacts=contacts,
                    commands=self.commands,
                    timestamp=time.time(),
                    head_rpy_offsets=self.head_teleop_client.get_rpy_offset(),
                )

                # self.action_filter.push(motor_targets)
                # motor_targets = self.action_filter.get_filtered_action()
                
                # Create joint dictionary for hardware interface
                joint_names = self.constants.JOINTS_ORDER
                action_dict = {joint_names[i]: motor_targets[i] for i in range(len(motor_targets))}
                
                # Filter action_dict to include only head/neck/tail joints if legs not enabled
                if not self.legs_enabled:
                    action_dict = {k: v for k, v in action_dict.items() if k in self.head_neck_tail_joints}
                
                # Send commands to hardware
                self.hwi.set_positions(action_dict)

                i += 1

                took = time.time() - t
                if (1 / self.control_freq - took) < 0:
                    print("Policy control budget exceeded by", np.around(took - 1 / self.control_freq, 3),)
                # print(took)
                time.sleep(max(0, 1 / self.control_freq - took))

        except KeyboardInterrupt:
            pass

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("-p", type=int, default=22)
    parser.add_argument("-i", type=int, default=0)
    parser.add_argument("-d", type=int, default=0)
    parser.add_argument("-c", "--control_freq", type=int, default=50)
    parser.add_argument(
        "--robot",
        type=str,
        default="mini2",
        choices=["mini2", "dino"],
        help="Robot type to use for the simulation.",
    )
    parser.add_argument(
        "--policy_type", 
        type=str, 
        default="standing", 
        choices=["episodic", "joystick", "standing"],
        help="Initial policy to use (episodic, joystick, standing)"
    )
    parser.add_argument(
        "--cutoff_freq", 
        type=float, 
        default=50.0, 
        help="Cutoff frequency for low-pass filter"
    )
    parser.add_argument(
        "--teleop_host", 
        type=str, 
        default="10.144.135.208", 
        help="Teleop controller's IP"
    )

    args = parser.parse_args()
    pid = [args.p, args.i, args.d]

    print("Done parsing args")
    rl_walk = RLWalk(
        control_freq=args.control_freq,
        pid=pid,
        robot=args.robot,
        initial_policy_type=args.policy_type,
        cutoff_freq=args.cutoff_freq,
        teleop_host=args.teleop_host
    )
    rl_walk.run()
