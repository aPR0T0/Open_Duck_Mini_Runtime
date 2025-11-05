import socket
import threading
import numpy as np
import time
import ipaddress
import concurrent.futures

class HeadTelop:
    def __init__(self, host=None, port=5000, retry_delay=1, max_retries=5):
        self.host = host
        self.port = port
        self.retry_delay = retry_delay
        self.max_retries = max_retries
        self._calibration_offset = None
        self.rpy_offset = (0.0, 0.0, 0.0)
        self._running = False
        self.roll_range = [-10, 10]
        self.pitch_range = [-10, 10]
        self.yaw_range = [-40, 40]
        self._thread = None

    def _get_local_subnet(self):
        """Detect local subnet (e.g., 192.168.1.0/24)"""
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
        finally:
            s.close()
        # assume /24 network mask
        return str(ipaddress.ip_network(local_ip + "/24", strict=False))

    def _find_server(self):
        """Scan local network for a device with open port 5000"""
        subnet = self._get_local_subnet()
        print(f"Scanning subnet {subnet} for port {self.port}...")
        for ip in ipaddress.IPv4Network(subnet, strict=False):
            ip = str(ip)
            print(f"scanning for ip : {ip}")
            try:
                # Use TCP (SOCK_STREAM), not UDP
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    socket.create_connection((str(ip), self.port), timeout=0.02)
                    print(f"✅ Found server at {ip}:{self.port}")
                    # s.connect((self.host, self.port))
                    return ip
            except (socket.timeout, ConnectionRefusedError, OSError):
                continue
        print("❌ No server found.")
        return None

    def start(self):  
        if self._thread is None or not self._thread.is_alive() or self._running is False:
            self._running = True
            self._thread = threading.Thread(target=self._run, daemon=True)
            
            self._thread.start()

    def stop(self):
        self._running = False
        if self._thread is not None:
            self._thread.join()
            self._thread = None

    def get_rpy_offset(self):
        return self.rpy_offset

    def _run(self):
        retry_count = 0

        while self._running:
            try:
                while self.host is None:
                    self.host = self._find_server()
                    if not self.host:
                        time.sleep(self.retry_delay)
                        continue

                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.connect((self.host, self.port))
                    print(f"Connected to server at {self.host}:{self.port}")
                    retry_count = 0

                    while self._running:
                        data = s.recv(1024)
                        if not data:
                            break

                        try:
                            yaw, pitch, roll = map(float, data.decode().strip().split(","))
                        except ValueError:
                            continue

                        if self._calibration_offset is None:
                            self._calibration_offset = (yaw, pitch, roll)
                            print("Calibration set:", self._calibration_offset)
                            continue

                        rel_yaw = -(self._calibration_offset[0] - yaw)
                        rel_pitch = self._calibration_offset[1] - pitch
                        rel_roll = self._calibration_offset[2] - roll

                        self.rpy_offset = np.deg2rad((
                            np.clip(rel_roll, *self.roll_range),
                            np.clip(rel_pitch, *self.pitch_range),
                            np.clip(rel_yaw, *self.yaw_range)
                        ))

                        print(rel_yaw)

            except (socket.error, ConnectionRefusedError, OSError) as e:
                if not self._running:
                    break

                retry_count += 1
                print(f"Connection failed: {e}")
                if self.max_retries is not None and retry_count > self.max_retries:
                    print(f"Max retries ({self.max_retries}) exceeded. Stopping.")
                    self._running = False
                    break

                print(f"Retrying in {self.retry_delay} seconds... (Attempt {retry_count})")
                time.sleep(self.retry_delay)
                self.host = None  # reset for re-scan next time