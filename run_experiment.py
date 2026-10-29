"""run_experiment.py  (Member 3 + 4) - launches the server and client processes.

  python run_experiment.py                 # clean measurements -> results.csv
  python run_experiment.py --rounds 30
  python run_experiment.py --demo          # all 5 clients AT ONCE (live demo)

Measurement mode runs the 5 client processes one after another per condition so
that clients don't queue behind each other at the server. --demo runs them in
parallel so the server window shows all timezones talking at once.
"""
import argparse, os, subprocess, sys, time

from profiles import PROFILES, CONDITIONS

HERE = os.path.dirname(os.path.abspath(__file__))


def client_cmd(region, cond, rounds, port, out, quiet):
    cmd = [sys.executable, os.path.join(HERE, "client.py"), "--region", region,
           "--condition", cond, "--rounds", str(rounds), "--port", str(port)]
    if out:
        cmd += ["--out", out]
    if quiet:
        cmd += ["--quiet"]
    return cmd


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=30)
    ap.add_argument("--port", type=int, default=9999)
    ap.add_argument("--out", default="results.csv")
    ap.add_argument("--demo", action="store_true", help="run all clients in parallel")
    a = ap.parse_args()

    if a.demo:
        a.out = None
    elif os.path.exists(a.out):
        os.remove(a.out)

    server_cmd = [sys.executable, os.path.join(HERE, "server.py"), "--port", str(a.port)]
    if not a.demo:
        server_cmd.append("--quiet")
    server = subprocess.Popen(server_cmd)
    time.sleep(0.5)                                   # let the server bind
    try:
        for cond in CONDITIONS:
            print(f"\n=== condition: {cond} ===", flush=True)
            if a.demo:
                procs = [subprocess.Popen(client_cmd(r, cond, a.rounds, a.port, a.out, False))
                         for r in PROFILES]
                for p in procs:
                    p.wait()
            else:
                for r in PROFILES:
                    print(f"  running {r} ...", flush=True)
                    subprocess.run(client_cmd(r, cond, a.rounds, a.port, a.out, True), check=True)
    finally:
        server.terminate()
        server.wait()
    if a.out:
        print(f"\nDone. Results in {a.out}")


if __name__ == "__main__":
    main()
