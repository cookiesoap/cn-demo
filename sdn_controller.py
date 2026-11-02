"""sdn_controller.py - Ryu (OpenFlow 1.3) controller: congestion-aware rerouting.

Control plane for the time-sync network built by sdn_topo.py.

  * On connect it proactively installs plain IP forwarding rules on every switch
    (all traffic uses the PRIMARY path  s1 - s2 - s4).
  * Every POLL seconds it asks s1 for port statistics of the primary uplink and
    computes link utilisation.
  * If utilisation stays above HIGH for HIGH_N polls -> CONGESTION: it installs
    higher-priority flows that move the UDP time-sync traffic (port 9999) onto the
    BACKUP path  s1 - s3 - s4.  Both directions are moved together, so the forward
    and return paths stay symmetric (path asymmetry is what ruins NTP-style sync).
  * When utilisation stays below LOW for LOW_N polls -> the override flows are
    deleted and sync traffic returns to the primary path.

Run:   ryu-manager sdn_controller.py
Off:   SDN_REROUTE=0 ryu-manager sdn_controller.py     (baseline: no congestion handling)
"""
import csv
import os
import time

from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, set_ev_cls
from ryu.lib import hub
from ryu.ofproto import ofproto_v1_3

# ---- must match sdn_topo.py --------------------------------------------------
SYNC_PORT = 9999                                   # UDP port of server.py
CLIENT_IPS = [f"10.0.0.{i}" for i in range(1, 7)]  # 5 regions + background source
SERVER_IP, SINK_IP = "10.0.0.7", "10.0.0.8"
LINK_MBPS = 10.0                                   # capacity of the primary uplink
MONITOR_DPID, MONITOR_PORT = 1, 7                  # s1 port 7 = primary uplink
BACKUP_PORT_S1, BACKUP_PORT_S4 = 8, 2              # s1->s3 , s4->s3

# ---- congestion policy -------------------------------------------------------
POLL = 1.0                  # seconds between statistics requests
HIGH, LOW = 0.70, 0.40      # utilisation thresholds (hysteresis avoids flapping)
HIGH_N, LOW_N = 2, 4        # consecutive polls needed before acting
REROUTE_ENABLED = os.environ.get("SDN_REROUTE", "1") != "0"
EVENT_LOG = os.environ.get("SDN_EVENT_LOG", "sdn_events.csv")

PRIO_DEFAULT, PRIO_REROUTE = 10, 100

# Static routing tables: dpid -> {destination ip: output port}
ROUTES = {
    1: {**{ip: i for i, ip in enumerate(CLIENT_IPS, 1)},      # hosts on ports 1..6
        SERVER_IP: 7, SINK_IP: 7},                             # primary uplink
    2: {**{ip: 1 for ip in CLIENT_IPS}, SERVER_IP: 2, SINK_IP: 2},
    3: {**{ip: 1 for ip in CLIENT_IPS}, SERVER_IP: 2, SINK_IP: 2},
    4: {**{ip: 1 for ip in CLIENT_IPS}, SERVER_IP: 3, SINK_IP: 4},  # replies use primary
}


class CongestionController(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.dps = {}                 # dpid -> datapath
        self.prev = None              # (time, tx_bytes) of the monitored port
        self.rerouted = False
        self.hi_count = 0
        self.lo_count = 0
        self.monitor_thread = hub.spawn(self._monitor)
        self._log("controller_start", 0.0,
                  f"reroute={'on' if REROUTE_ENABLED else 'off'}")

    # ------------------------------------------------------------------ helpers
    def _log(self, event, util, note=""):
        new = not os.path.exists(EVENT_LOG)
        with open(EVENT_LOG, "a", newline="") as f:
            w = csv.writer(f)
            if new:
                w.writerow(["time", "event", "utilisation", "note"])
            w.writerow([f"{time.time():.3f}", event, f"{util:.3f}", note])
        self.logger.info("%s util=%.0f%% %s", event, util * 100, note)

    def _add_flow(self, dp, priority, match, out_port):
        p = dp.ofproto_parser
        actions = [p.OFPActionOutput(out_port)]
        inst = [p.OFPInstructionActions(dp.ofproto.OFPIT_APPLY_ACTIONS, actions)]
        dp.send_msg(p.OFPFlowMod(datapath=dp, priority=priority, match=match,
                                 instructions=inst))

    def _del_flow(self, dp, priority, match):
        p, o = dp.ofproto_parser, dp.ofproto
        dp.send_msg(p.OFPFlowMod(datapath=dp, command=o.OFPFC_DELETE_STRICT,
                                 priority=priority, match=match,
                                 out_port=o.OFPP_ANY, out_group=o.OFPG_ANY))

    # ------------------------------------------------- 1. proactive base routing
    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def on_switch_features(self, ev):
        dp = ev.msg.datapath
        self.dps[dp.id] = dp
        p = dp.ofproto_parser
        for ip, port in ROUTES.get(dp.id, {}).items():
            match = p.OFPMatch(eth_type=0x0800, ipv4_dst=ip)
            self._add_flow(dp, PRIO_DEFAULT, match, port)
        self._log("switch_ready", 0.0, f"dpid={dp.id}")

    # --------------------------------------- 2. monitoring loop (statistics poll)
    def _monitor(self):
        while True:
            hub.sleep(POLL)
            dp = self.dps.get(MONITOR_DPID)
            if dp is None:
                continue
            p = dp.ofproto_parser
            dp.send_msg(p.OFPPortStatsRequest(dp, 0, MONITOR_PORT))

    @set_ev_cls(ofp_event.EventOFPPortStatsReply, MAIN_DISPATCHER)
    def on_port_stats(self, ev):
        if ev.msg.datapath.id != MONITOR_DPID:
            return
        for st in ev.msg.body:
            if st.port_no != MONITOR_PORT:
                continue
            now = time.time()
            if self.prev is not None:
                dt = now - self.prev[0]
                mbps = (st.tx_bytes - self.prev[1]) * 8 / dt / 1e6
                self._decide(mbps / LINK_MBPS)
            self.prev = (now, st.tx_bytes)

    # ----------------------------------------------- 3. congestion decision logic
    def _decide(self, util):
        self.hi_count = self.hi_count + 1 if util > HIGH else 0
        self.lo_count = self.lo_count + 1 if util < LOW else 0
        if not REROUTE_ENABLED:
            return
        if not self.rerouted and self.hi_count >= HIGH_N:
            self._set_reroute(True)
            self._log("CONGESTION_reroute_to_backup", util)
        elif self.rerouted and self.lo_count >= LOW_N:
            self._set_reroute(False)
            self._log("CLEAR_back_to_primary", util)

    # ------------------------------------- 4. push / remove the override flows
    def _set_reroute(self, on):
        """Move UDP time-sync traffic (both directions) to the backup path."""
        self.rerouted = on
        self.hi_count = self.lo_count = 0
        s1, s4 = self.dps.get(1), self.dps.get(4)
        if s1 is None or s4 is None:
            return
        # client -> server : s1 sends UDP dst-port 9999 via the backup uplink
        m1 = s1.ofproto_parser.OFPMatch(eth_type=0x0800, ip_proto=17, udp_dst=SYNC_PORT)
        # server -> client : s4 sends UDP src-port 9999 back via the backup path
        m4 = s4.ofproto_parser.OFPMatch(eth_type=0x0800, ip_proto=17, udp_src=SYNC_PORT)
        if on:
            self._add_flow(s1, PRIO_REROUTE, m1, BACKUP_PORT_S1)
            self._add_flow(s4, PRIO_REROUTE, m4, BACKUP_PORT_S4)
        else:
            self._del_flow(s1, PRIO_REROUTE, m1)
            self._del_flow(s4, PRIO_REROUTE, m4)
