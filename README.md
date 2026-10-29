# Network Time Synchronization System (UDP, multi-timezone)

Files: server.py (M1) | client.py (M2) | profiles.py (M3) | run_experiment.py (M3+M4) | analyze.py (M4)
Needs Python 3.9+ ; analysis needs `pip install pandas matplotlib`.

## Run
Live demo (7 terminals' worth, or just use --demo):
    python server.py
    python client.py --region Delhi   --condition normal --rounds 10
    python client.py --region Sydney  --condition congested --rounds 10
    (one terminal per region, each is a separate client process)

Everything automatically, parallel clients (demo):
    python run_experiment.py --demo --rounds 5

Clean measurements -> results.csv (clients run one after another):
    python run_experiment.py --rounds 30
    python analyze.py            # tables + graphs in ./analysis
