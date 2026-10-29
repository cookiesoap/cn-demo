"""server.py  (Member 1) - UTC reference time server over UDP.

Always uses time.time() (UTC epoch seconds). Never uses local time.
Request : {"id": "...", "tz": "...", "seq": n}
Reply   : {"seq": n, "t2": server_receive_time, "t3": server_send_time}
"""
import argparse, json, socket, time
from collections import defaultdict


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=9999)
    ap.add_argument("--quiet", action="store_true", help="don't print every request")
    args = ap.parse_args()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((args.host, args.port))
    print(f"[server] UTC reference server on {args.host}:{args.port}", flush=True)

    counts = defaultdict(int)
    try:
        while True:
            data, addr = sock.recvfrom(1024)
            t2 = time.time()                       # receive time (UTC)
            try:
                req = json.loads(data)
                cid, tz, seq = req["id"], req.get("tz", "?"), req.get("seq", 0)
            except (ValueError, KeyError):
                continue                           # ignore malformed packets
            counts[(cid, tz)] += 1
            t3 = time.time()                       # send time (UTC)
            sock.sendto(json.dumps({"seq": seq, "t2": t2, "t3": t3}).encode(), addr)
            if not args.quiet:
                print(f"[server] {cid:>8} [{tz}] port {addr[1]} seq {seq}", flush=True)
    except KeyboardInterrupt:
        print("\n[server] requests served per client:")
        for (cid, tz), n in sorted(counts.items()):
            print(f"   {cid:>8} [{tz}] : {n}")


if __name__ == "__main__":
    main()
