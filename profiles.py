"""profiles.py  (Member 3) - region and network-condition tables.

Everything about "where the client is" and "how bad the network is" lives here.
Delays are ONE-WAY, in seconds.
"""
import random

PROFILES = {
    "Delhi":   {"tz": "Asia/Kolkata",     "skew": +1.8, "delay": 0.010, "jitter": 0.002},
    "London":  {"tz": "Europe/London",    "skew": -0.9, "delay": 0.070, "jitter": 0.008},
    "NewYork": {"tz": "America/New_York", "skew": +2.3, "delay": 0.110, "jitter": 0.010},
    "Tokyo":   {"tz": "Asia/Tokyo",       "skew": -1.1, "delay": 0.060, "jitter": 0.006},
    "Sydney":  {"tz": "Australia/Sydney", "skew": +0.5, "delay": 0.130, "jitter": 0.012},
}

# asym: forward path is (1+asym)x the base delay, return path is (1-asym)x
# loss: probability that a round's reply is lost
CONDITIONS = {
    "normal":    {"delay_mult": 1.0, "jitter_mult": 1.0, "asym": 0.0, "loss": 0.00},
    "delayed":   {"delay_mult": 2.0, "jitter_mult": 2.0, "asym": 0.0, "loss": 0.00},
    "congested": {"delay_mult": 3.0, "jitter_mult": 6.0, "asym": 0.5, "loss": 0.05},
}


def sample_delays(profile, cond):
    """Return (forward_delay, return_delay) in seconds for one exchange."""
    base = profile["delay"] * cond["delay_mult"]
    j = profile["jitter"] * cond["jitter_mult"]
    fwd = max(0.0, random.gauss(base * (1 + cond["asym"]), j))
    back = max(0.0, random.gauss(base * (1 - cond["asym"]), j))
    return fwd, back
