"""sdn_client.py - time-sync client for the SDN testbed.

Same 4-timestamp exchange as client.py, but with NO simulated delay/loss: the
RTT, jitter and loss come from the real (emulated) Mininet network.

  python sdn_client.py --region Delhi --server 10.0.0.7 --rounds 20 --tag congested --out results_sdn.csv
"""
import argparse, csv, os, socket, time

from client import SimClock, sync_once
from profiles import PROFILES

FIELDS = ["tag", "region", "round", "lost", "rtt_ms", "offset_ms", "error_after_ms"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--region", choices=list(PROFILES), required=True)
    ap.add_argument("--server", default="10.0.0.7")
    ap.add_argument("--port", type=int, default=9999)
    ap.add_argument("--rounds", type=int, default=20)
    ap.add_argument("--tag", default="run", help="label for this phase (idle/congested/...)")
    ap.add_argument("--timeout", type=float, default=1.0)
    ap.add_argument("--gap", type=float, default=0.1)
    ap.add_argument("--out", default="results_sdn.csv")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()

    prof = PROFILES[a.region]
    clock = SimClock(prof["skew"])                    # every host needs its own "wrong" clock
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(a.timeout)
    rows = []
    for i in range(1, a.rounds + 1):
        res = sync_once(sock, (a.server, a.port), clock, a.region, prof["tz"], i)
        if res is None:
            rows.append(dict(tag=a.tag, region=a.region, round=i, lost=1,
                             rtt_ms="", offset_ms="", error_after_ms=""))
            if not a.quiet:
                print(f"[{a.region}] round {i:>2}: LOST")
        else:
            offset, rtt = res
            err = abs(clock.now() + offset - time.time())
            rows.append(dict(tag=a.tag, region=a.region, round=i, lost=0,
                             rtt_ms=f"{rtt*1000:.2f}", offset_ms=f"{offset*1000:.2f}",
                             error_after_ms=f"{err*1000:.2f}"))
            if not a.quiet:
                print(f"[{a.region}] round {i:>2}: rtt={rtt*1000:7.1f}ms "
                      f"err_after={err*1000:6.2f}ms")
        time.sleep(a.gap)
    sock.close()

    new = not os.path.exists(a.out)
    with open(a.out, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        w.writerows(rows)


if __name__ == "__main__":
    main()
