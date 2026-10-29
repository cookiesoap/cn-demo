"""client.py  (Member 2) - simulated client with its own wrong clock.

Each running copy of this script is ONE client process pretending to be a machine
in one city. It does the 4-timestamp exchange, computes RTT and offset, and
shows the corrected time in its own timezone.

Examples
  python client.py --region Delhi --condition normal --rounds 5
  python client.py --id Test --tz Asia/Tokyo --skew -1.1 --delay 0.06 --jitter 0.006
"""
import argparse, csv, json, os, random, socket, time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from profiles import PROFILES, CONDITIONS, sample_delays

FIELDS = ["region", "tz", "condition", "round", "lost", "fwd_delay", "back_delay",
          "offset", "rtt", "error_before", "error_after", "signed_error_after",
          "naive_error"]


class SimClock:
    """A wrong clock: real time + fixed skew + optional drift (ppm)."""
    def __init__(self, skew=0.0, drift_ppm=0.0):
        self.skew = skew
        self.drift = drift_ppm / 1e6
        self.t0 = time.time()

    def now(self):
        t = time.time()
        return t + self.skew + (t - self.t0) * self.drift


def sync_once(sock, server, clock, cid, tz, seq, fwd=0.0, back=0.0, lose=False):
    """One NTP-style exchange. Returns (offset, delay) or None if the reply was lost.

    t1 client send (client clock)   t2 server receive (server clock)
    t3 server send (server clock)   t4 client receive (client clock)
    """
    t1 = clock.now()
    time.sleep(fwd)                                   # simulated forward delay
    sock.sendto(json.dumps({"id": cid, "tz": tz, "seq": seq}).encode(), server)
    try:
        while True:
            data, _ = sock.recvfrom(1024)
            r = json.loads(data)
            if r.get("seq") == seq:                   # ignore stale replies
                break
    except socket.timeout:
        return None
    if lose:                                          # simulate a dropped reply
        return None
    time.sleep(back)                                  # simulated return delay
    t4 = clock.now()
    t2, t3 = r["t2"], r["t3"]
    offset = ((t2 - t1) + (t3 - t4)) / 2
    delay = (t4 - t1) - (t3 - t2)
    return offset, delay


def show_local(clock, offset, tz):
    """Synchronise in UTC, convert to the client's timezone only for display."""
    synced_utc = clock.now() + offset
    return datetime.fromtimestamp(synced_utc, ZoneInfo(tz)).isoformat(timespec="milliseconds")


def naive_error(clock, offset, tz):
    """Demo of the timezone bug: take the correctly synced local wall-clock
    digits and mistakenly read them as UTC. Error = the timezone's UTC offset."""
    synced_utc = clock.now() + offset
    wall = datetime.fromtimestamp(synced_utc, ZoneInfo(tz)).replace(tzinfo=None)
    wrong_epoch = wall.replace(tzinfo=timezone.utc).timestamp()
    return abs(wrong_epoch - time.time())


def run_client(region, tz, skew, delay, jitter, condition, rounds, port,
               out=None, verbose=True, gap=0.02):
    cond = CONDITIONS[condition]
    profile = {"delay": delay, "jitter": jitter}
    clock = SimClock(skew)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(2.0)
    server = ("127.0.0.1", port)
    rows = []
    for i in range(1, rounds + 1):
        fwd, back = sample_delays(profile, cond)
        lose = random.random() < cond["loss"]
        res = sync_once(sock, server, clock, region, tz, i, fwd, back, lose)
        if res is None:
            row = dict(region=region, tz=tz, condition=condition, round=i, lost=1,
                       fwd_delay=fwd, back_delay=back, offset="", rtt="",
                       error_before="", error_after="", signed_error_after="",
                       naive_error="")
            if verbose:
                print(f"[{region}] round {i:>2}: LOST")
        else:
            offset, rtt = res
            true_now = time.time()
            before = clock.now() - true_now
            after = clock.now() + offset - true_now
            row = dict(region=region, tz=tz, condition=condition, round=i, lost=0,
                       fwd_delay=fwd, back_delay=back, offset=offset, rtt=rtt,
                       error_before=abs(before), error_after=abs(after),
                       signed_error_after=after,
                       naive_error=naive_error(clock, offset, tz))
            if verbose:
                print(f"[{region}] round {i:>2}: offset={offset:+.4f}s rtt={rtt*1000:6.1f}ms "
                      f"err_before={abs(before)*1000:8.1f}ms err_after={abs(after)*1000:6.2f}ms "
                      f"local={show_local(clock, offset, tz)}")
        rows.append(row)
        time.sleep(gap)
    sock.close()
    if out:
        new = not os.path.exists(out)
        with open(out, "a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            if new:
                w.writeheader()
            w.writerows(rows)
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--region", choices=list(PROFILES), help="load defaults from profiles.py")
    ap.add_argument("--id", help="client name (default: region)")
    ap.add_argument("--tz")
    ap.add_argument("--skew", type=float)
    ap.add_argument("--delay", type=float, help="one-way base delay (s)")
    ap.add_argument("--jitter", type=float)
    ap.add_argument("--condition", choices=list(CONDITIONS), default="normal")
    ap.add_argument("--rounds", type=int, default=10)
    ap.add_argument("--port", type=int, default=9999)
    ap.add_argument("--out", help="append results to this CSV")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()

    p = PROFILES.get(a.region, {})
    tz = a.tz or p.get("tz")
    skew = a.skew if a.skew is not None else p.get("skew", 0.0)
    delay = a.delay if a.delay is not None else p.get("delay", 0.01)
    jitter = a.jitter if a.jitter is not None else p.get("jitter", 0.002)
    cid = a.id or a.region
    if not (cid and tz):
        ap.error("give --region, or both --id and --tz")
    run_client(cid, tz, skew, delay, jitter, a.condition, a.rounds, a.port,
               out=a.out, verbose=not a.quiet)


if __name__ == "__main__":
    main()
