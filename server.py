"""
Member 1 - Reference Server
Network Time Synchronization System (UDP)

The server acts as the reference clock. For every request it receives from
a client it replies with:
    t1 : client send time   (echoed back from the request)
    t2 : server receive time
    t3 : server transmit time (the server timestamp)

The client (Member 2) uses t1..t4 to calculate RTT and clock offset.

Run:  python server.py
      python server.py --host 0.0.0.0 --port 5005
"""

import argparse
import json
import socket
import time

BUFFER_SIZE = 1024


def now():
    """Reference time of the server (seconds since epoch, high resolution)."""
    return time.time()


def run_server(host, port):
    # Create a UDP socket
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    server_socket.bind((host, port))

    print("=" * 55)
    print(" Reference Time Server started (UDP)")
    print(f" Listening on {host}:{port}")
    print(" Press Ctrl+C to stop")
    print("=" * 55)

    request_count = 0
    clients_seen = set()

    try:
        while True:
            # Wait for a request from any client
            data, client_addr = server_socket.recvfrom(BUFFER_SIZE)
            t2 = now()  # server receive time

            try:
                request = json.loads(data.decode("utf-8"))
                t1 = request.get("t1")  # client send time
            except (ValueError, UnicodeDecodeError):
                print(f"[!] Invalid request from {client_addr}, ignored")
                continue

            request_count += 1
            if client_addr not in clients_seen:
                clients_seen.add(client_addr)
                print(f"[+] New client connected: {client_addr}")

            # Build the reply with the server timestamps
            t3 = now()  # server transmit time
            reply = {
                "t1": t1,
                "t2": t2,
                "t3": t3,
                "server_time": t3,
            }
            server_socket.sendto(json.dumps(reply).encode("utf-8"), client_addr)

            print(
                f"[{request_count:04d}] {client_addr[0]}:{client_addr[1]} | "
                f"t2={t2:.6f} | t3={t3:.6f} | "
                f"processing={(t3 - t2) * 1000:.3f} ms"
            )

    except KeyboardInterrupt:
        print("\nShutting down server...")
    finally:
        server_socket.close()
        print(f"Total requests served: {request_count}")
        print(f"Total unique clients : {len(clients_seen)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="UDP Reference Time Server")
    parser.add_argument("--host", default="0.0.0.0", help="IP to bind (default 0.0.0.0)")
    parser.add_argument("--port", type=int, default=5005, help="UDP port (default 5005)")
    args = parser.parse_args()

    run_server(args.host, args.port)
