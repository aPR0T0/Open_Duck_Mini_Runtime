#!/usr/bin/env python3
import subprocess
import json
import socket

HOST = "0.0.0.0"
PORT = 5000

def clear_sensor_cache():
    subprocess.run(["termux-sensor", "-c"], check=False)

def start_sensor_stream():
    return subprocess.Popen(
        ["termux-sensor", "-s", "Rotation", "-d", "20"],
        stdout=subprocess.PIPE,
        text=True,
        bufsize=1
    )

def start_server():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((HOST, PORT))
    sock.listen(1)
    print(f"📡 Server listening on {HOST}:{PORT}")
    return sock

def main():
    clear_sensor_cache()
    process = start_sensor_stream()
    sock = start_server()

    conn = None
    buffer = ""

    while True:
        if conn is None:
            print("🕓 Waiting for client...")
            conn, addr = sock.accept()
            print(f"✅ Client connected: {addr}")

        try:
            line = process.stdout.readline()
            if not line:
                continue

            buffer += line.strip()
            if buffer.startswith("{") and buffer.endswith("}"):
                try:
                    data = json.loads(buffer)
                    buffer = ""
                except json.JSONDecodeError:
                    continue

                if not data:
                    continue

                sensor_name = list(data.keys())[0]
                values = data[sensor_name]["values"]
                yaw, pitch, roll = values[0], values[1], values[2]
                msg = f"{yaw},{pitch},{roll}\n"

                try:
                    conn.sendall(msg.encode("utf-8"))
                    print("📤 Sent:", msg.strip())
                except (BrokenPipeError, ConnectionResetError):
                    print("⚠️ Client disconnected. Reopening socket...")
                    conn.close()
                    conn = None

        except KeyboardInterrupt:
            print("🛑 Stopping...")
            break

    process.terminate()
    if conn:
        conn.close()
    sock.close()

if __name__ == "__main__":
    main()
