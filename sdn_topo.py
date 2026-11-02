"""sdn_topo.py - Mininet testbed + automatic congestion experiment.

                         primary (10 Mbps, bottleneck)
   Delhi ---+                 +-- s2 --+
   London --+                 |        |
   NewYork -+-- s1 -----------+        +-- s4 --- time server (10.0.0.7)
   Tokyo ---+    |            |        |      \\-- iperf sink  (10.0.0.8)
   Sydney --+    |            +-- s3 --+
   bg host -+    +--------------- backup (10 Mbps)

Per-region one-way delay/jitter on the host links come from profiles.py.
The background host floods the primary path with UDP to create congestion; the
Ryu controller (sdn_controller.py) detects it and moves the time-sync flows to
the backup path.

Usage (two terminals, both need root):
    1)  ryu-manager sdn_controller.py              # or: SDN_REROUTE=0 ryu-manager ...
    2)  sudo python3 sdn_topo.py                   # runs the experiment
        sudo python3 sdn_topo.py --cli             # drop into the Mininet CLI instead
"""
import argparse, csv, os, statistics, time
from collections import defaultdict

from mininet.cli import CLI
from mininet.link import TCLink
from mininet.log import setLogLevel
from mininet.net import Mininet
from mininet.node import OVSKernelSwitch, RemoteController

from profiles import PROFILES

HERE = os.path.dirname(os.path.abspath(__file__))
REGIONS = list(PROFILES)                        # Delhi, London, NewYork, Tokyo, Sydney


def build(controller_ip, controller_port):
    net = Mininet(controller=None, switch=OVSKernelSwitch, link=TCLink,
                  autoSetMacs=False, autoStaticArp=False)
    net.addController("c0", controller=RemoteController, ip=controller_ip,
                      port=controller_port, protocols="OpenFlow13")
    sw = {n: net.addSwitch(n, dpid=str(i), protocols="OpenFlow13")
          for i, n in enumerate(["s1", "s2", "s3", "s4"], 1)}

    def host(name, n):
        return net.addHost(name, ip=f"10.0.0.{n}/24", mac=f"00:00:00:00:00:{n:02x}")

    hosts = {r: host(r.lower(), i) for i, r in enumerate(REGIONS, 1)}
    bg = host("bg", 6)
    server = host("server", 7)
    sink = host("sink", 8)

    # access links: ports 1..6 on s1 (region delay/jitter from profiles.py)
    for i, r in enumerate(REGIONS, 1):
        p = PROFILES[r]
        net.addLink(hosts[r], sw["s1"], port2=i, bw=100,
                    delay=f"{p['delay']*1000:.1f}ms", jitter=f"{p['jitter']*1000:.1f}ms")
    net.addLink(bg, sw["s1"], port2=6, bw=100)
    # core: port numbers must match sdn_controller.py
    net.addLink(sw["s1"], sw["s2"], port1=7, port2=1, bw=10, delay="5ms", max_queue_size=200)  # primary
    net.addLink(sw["s1"], sw["s3"], port1=8, port2=1, bw=10, delay="5ms", max_queue_size=200)  # backup
    net.addLink(sw["s2"], sw["s4"], port1=2, port2=1, bw=100, delay="1ms")
    net.addLink(sw["s3"], sw["s4"], port1=2, port2=2, bw=100, delay="1ms")
    net.addLink(server, sw["s4"], port2=3, bw=100, delay="1ms")
    net.addLink(sink, sw["s4"], port2=4, bw=100)
    return net, hosts, bg, server, sink


def run_clients(hosts, tag, rounds, out):
    for r, h in hosts.items():
        h.cmd(f"cd {HERE} && python3 sdn_client.py --region {r} --server 10.0.0.7 "
              f"--rounds {rounds} --tag {tag} --out {out} --quiet")


def summarize(out):
    stats = defaultdict(lambda: dict(rtt=[], err=[], lost=0, n=0))
    with open(out) as f:
        for row in csv.DictReader(f):
            s = stats[row["tag"]]
            s["n"] += 1
            if row["lost"] == "1":
                s["lost"] += 1
            else:
                s["rtt"].append(float(row["rtt_ms"]))
                s["err"].append(float(row["error_after_ms"]))
    print(f"\n{'phase':<14}{'mean RTT ms':>12}{'max RTT ms':>12}{'loss %':>9}{'mean err ms':>13}")
    for tag, s in stats.items():
        if s["rtt"]:
            print(f"{tag:<14}{statistics.mean(s['rtt']):>12.1f}{max(s['rtt']):>12.1f}"
                  f"{100*s['lost']/s['n']:>9.1f}{statistics.mean(s['err']):>13.2f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--controller", default="127.0.0.1")
    ap.add_argument("--cport", type=int, default=6653)
    ap.add_argument("--rounds", type=int, default=20)
    ap.add_argument("--load", default="9M", help="background UDP rate (primary link is 10M)")
    ap.add_argument("--settle", type=int, default=6, help="seconds to let the controller react")
    ap.add_argument("--out", default=os.path.join(HERE, "results_sdn.csv"))
    ap.add_argument("--cli", action="store_true")
    a = ap.parse_args()

    setLogLevel("info")
    net, hosts, bg, server, sink = build(a.controller, a.cport)
    net.start()
    net.staticArp()          # no ARP flooding: the s1-s2-s4-s3 loop would storm
    time.sleep(2)            # let the controller push its flows
    if os.path.exists(a.out):
        os.remove(a.out)
    try:
        server.cmd(f"cd {HERE} && python3 server.py --host 10.0.0.7 --quiet "
                   f"> /tmp/sdn_server.log 2>&1 &")
        time.sleep(1)
        if a.cli:
            CLI(net)
            return

        print("\n[1/3] idle network")
        run_clients(hosts, "idle", a.rounds, a.out)

        print(f"[2/3] background load {a.load} on the primary path "
              f"(waiting {a.settle}s for the controller to react)")
        sink.cmd("iperf -s -u > /tmp/sdn_iperf_sink.log 2>&1 &")
        bg.cmd(f"iperf -c 10.0.0.8 -u -b {a.load} -t 600 > /tmp/sdn_iperf_bg.log 2>&1 &")
        time.sleep(a.settle)
        run_clients(hosts, "congested", a.rounds, a.out)

        print("[3/3] load stopped")
        bg.cmd("pkill iperf; true")
        sink.cmd("pkill iperf; true")
        time.sleep(a.settle + 3)
        run_clients(hosts, "recovered", a.rounds, a.out)

        summarize(a.out)
        print(f"\nRaw samples: {a.out}\nController events: sdn_events.csv")
    finally:
        net.stop()


if __name__ == "__main__":
    main()
