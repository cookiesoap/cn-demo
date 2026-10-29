"""analyze.py  (Member 4) - tables and graphs from results.csv"""
import sys, os
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

CSV = sys.argv[1] if len(sys.argv) > 1 else "results.csv"
OUT = "analysis"
os.makedirs(OUT, exist_ok=True)

REGIONS = ["Delhi", "London", "Tokyo", "NewYork", "Sydney"]   # near -> far
CONDS = ["normal", "delayed", "congested"]
COLORS = {"normal": "#2a9d8f", "delayed": "#e9c46a", "congested": "#e76f51"}

df = pd.read_csv(CSV)
total = len(df)
lost = int(df["lost"].sum())
ok = df[df["lost"] == 0].copy()
for c in ["offset", "rtt", "error_before", "error_after", "signed_error_after", "naive_error"]:
    ok[c] = pd.to_numeric(ok[c])
for c in ["error_before", "error_after", "rtt", "signed_error_after", "naive_error"]:
    ok[c + "_ms"] = ok[c] * 1000

print(f"{total} rounds, {lost} lost ({lost/total:.1%}), {len(ok)} used\n")

# ---- Table 1: error by region x condition ------------------------------------
t1 = (ok.groupby(["region", "condition"])
        .agg(mean_rtt_ms=("rtt_ms", "mean"),
             mean_error_ms=("error_after_ms", "mean"),
             max_error_ms=("error_after_ms", "max"),
             rounds=("round", "count"))
        .round(2).reset_index())
t1["region"] = pd.Categorical(t1["region"], REGIONS, ordered=True)
t1["condition"] = pd.Categorical(t1["condition"], CONDS, ordered=True)
t1 = t1.sort_values(["condition", "region"])
t1.to_csv(f"{OUT}/table_error_by_region_condition.csv", index=False)
print("TABLE 1 - error after sync (ms)\n", t1.to_string(index=False), "\n")

# ---- Table 2: naive vs UTC ------------------------------------------------------
t2 = (ok[ok.condition == "normal"].groupby("region")
        .agg(tz=("tz", "first"),
             before_sync_s=("error_before", "mean"),
             utc_sync_error_ms=("error_after_ms", "mean"),
             naive_local_error_s=("naive_error", "mean"))
        .reindex(REGIONS).round(4).reset_index())
t2["naive_local_error_h"] = (t2["naive_local_error_s"] / 3600).round(2)
t2.to_csv(f"{OUT}/table_naive_vs_utc.csv", index=False)
print("TABLE 2 - naive local-time vs UTC sync (normal network)\n", t2.to_string(index=False), "\n")

# ---- Table 3: low-RTT filter ----------------------------------------------------
W = 5
recs = []
for (r, c), g in ok.groupby(["region", "condition"]):
    g = g.sort_values("round").reset_index(drop=True)
    for i in range(0, len(g) - W + 1, W):
        win = g.iloc[i:i + W]
        best = win.loc[win["rtt"].idxmin()]
        recs.append(dict(region=r, condition=c,
                         plain=win["error_after_ms"].mean(),
                         filtered=best["error_after_ms"]))
f = pd.DataFrame(recs)
t3 = f.groupby(["condition", "region"]).mean().round(2).reset_index()
t3["condition"] = pd.Categorical(t3["condition"], CONDS, ordered=True)
t3["region"] = pd.Categorical(t3["region"], REGIONS, ordered=True)
t3 = t3.sort_values(["condition", "region"])
t3.to_csv(f"{OUT}/table_lowrtt_filter.csv", index=False)
print(f"TABLE 3 - mean error (ms): plain vs lowest-RTT-of-{W}\n", t3.to_string(index=False), "\n")

# ---- Graph 1: error per region, grouped by condition ----------------------------
fig, ax = plt.subplots(figsize=(9, 5))
w = 0.26
for k, c in enumerate(CONDS):
    vals = [t1[(t1.region == r) & (t1.condition == c)]["mean_error_ms"].iloc[0] for r in REGIONS]
    ax.bar([i + (k - 1) * w for i in range(len(REGIONS))], vals, w, label=c, color=COLORS[c])
ax.set_xticks(range(len(REGIONS)))
ax.set_xticklabels(REGIONS)
ax.set_ylabel("Mean synchronization error (ms)")
ax.set_title("Synchronization error by region and network condition")
ax.legend(); ax.grid(axis="y", alpha=.3)
fig.tight_layout(); fig.savefig(f"{OUT}/1_error_by_region_condition.png", dpi=150); plt.close(fig)

# ---- Graph 2: RTT vs error --------------------------------------------------------
fig, ax = plt.subplots(figsize=(8, 5))
for c in CONDS:
    s = ok[ok.condition == c]
    ax.scatter(s["rtt_ms"], s["error_after_ms"], s=14, alpha=.6, label=c, color=COLORS[c])
ax.set_xlabel("Measured RTT (ms)"); ax.set_ylabel("Synchronization error (ms)")
ax.set_title("Higher RTT and asymmetry give larger error")
ax.legend(); ax.grid(alpha=.3)
fig.tight_layout(); fig.savefig(f"{OUT}/2_rtt_vs_error.png", dpi=150); plt.close(fig)

# ---- Graph 3: before vs after sync (normal) ---------------------------------------
fig, ax = plt.subplots(figsize=(8, 5))
n = ok[ok.condition == "normal"].groupby("region")[["error_before_ms", "error_after_ms"]].mean().reindex(REGIONS)
x = range(len(REGIONS))
ax.bar([i - .2 for i in x], n["error_before_ms"], .4, label="before sync", color="#adb5bd")
ax.bar([i + .2 for i in x], n["error_after_ms"], .4, label="after sync", color="#2a9d8f")
ax.set_yscale("log"); ax.set_xticks(list(x)); ax.set_xticklabels(REGIONS)
ax.set_ylabel("|clock error| (ms, log scale)")
ax.set_title("Clock error before vs after synchronization (normal network)")
ax.legend(); ax.grid(axis="y", alpha=.3)
fig.tight_layout(); fig.savefig(f"{OUT}/3_before_vs_after.png", dpi=150); plt.close(fig)

# ---- Graph 4: naive vs UTC ---------------------------------------------------------
fig, ax = plt.subplots(figsize=(8, 5))
ax.bar([i - .2 for i in x], t2["naive_local_error_s"] * 1000, .4, label="naive local-time", color="#e76f51")
ax.bar([i + .2 for i in x], t2["utc_sync_error_ms"], .4, label="UTC-based sync", color="#2a9d8f")
ax.set_yscale("log"); ax.set_xticks(list(x)); ax.set_xticklabels([f"{r}\n({tz})" for r, tz in zip(t2.region, t2.tz)], fontsize=8)
ax.set_ylabel("Error (ms, log scale)")
ax.set_title("Timezone-naive vs UTC-based time handling")
ax.legend(); ax.grid(axis="y", alpha=.3)
fig.tight_layout(); fig.savefig(f"{OUT}/4_naive_vs_utc.png", dpi=150); plt.close(fig)

# ---- Graph 5: low-RTT filter (congested) --------------------------------------------
fig, ax = plt.subplots(figsize=(8, 5))
c5 = t3[t3.condition == "congested"].set_index("region").reindex(REGIONS)
ax.bar([i - .2 for i in x], c5["plain"], .4, label="average of 5 samples", color="#e76f51")
ax.bar([i + .2 for i in x], c5["filtered"], .4, label=f"lowest-RTT of 5", color="#264653")
ax.set_xticks(list(x)); ax.set_xticklabels(REGIONS)
ax.set_ylabel("Mean error (ms)"); ax.set_title("Congested network: effect of lowest-RTT sample selection")
ax.legend(); ax.grid(axis="y", alpha=.3)
fig.tight_layout(); fig.savefig(f"{OUT}/5_lowrtt_filter_congested.png", dpi=150); plt.close(fig)

print(f"Graphs and tables saved in ./{OUT}/")
