"""Simulated IoT / stakeholder event feed for VOC Port, Thoothukudi.

In production these events would come from the port's RFID gate system,
berth sensors and GPS trackers. Here a script plays that role, walking one
(or more) containers through the full lifecycle against the running backend.

Usage:
    python iot_simulator/simulate.py                 # 1 container, ~24s journey
    python iot_simulator/simulate.py --fast          # ~2s journey
    python iot_simulator/simulate.py --containers 5  # 5 random journeys
"""
import argparse
import json
import random
import time
import urllib.request

BASE = "http://localhost:5000"
VESSELS = ["MV Coromandel Trader", "MV Gulf Pearl", "MV Tamil Nadu Star",
           "MV Palk Strait", "MV Manapad Point"]
EXPORTS = [("Seafood", "Reefer"), ("Granite", "Dry"), ("Salt", "Dry"),
           ("Sugar", "Dry"), ("Textiles", "Dry")]
IMPORTS = [("Coal", "Dry"), ("Machinery", "ODC"), ("Electronics", "Dry"),
           ("Chemicals", "Hazardous"), ("Timber", "Dry")]

def send(payload):
    req = urllib.request.Request(
        BASE + "/api/event", data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {"ok": False, "error": json.loads(e.read())["error"]}

def journey(step, cid=None):
    cid = cid or "TUTU" + "".join(random.choice("0123456789") for _ in range(7))
    trade = "Export" if random.random() < 0.5 else "Import"
    cat, ctype = random.choice(EXPORTS if trade == "Export" else IMPORTS)
    terminal = random.choice(["PSA_SICAL", "DBGT"])
    vessel = random.choice(VESSELS)
    print(f"\n=== Container {cid} · {trade} · {cat} ({ctype}) · {terminal} · {vessel} ===")

    # 1. ARRIVED — fired by the IoT layer (SYSTEM role)
    r = send({"container_id": cid, "event": "ARRIVED", "role": "SYSTEM",
              "details": {"vessel": vessel, "terminal": terminal, "trade": trade,
                          "cargo_category": cat, "cargo_type": ctype,
                          "arrival_date": time.strftime("%Y-%m-%d"),
                          "berth": "Inner Harbour Berth IX"}})
    print(f"  ARRIVED          -> predicted delay: "
          f"{r.get('prediction',{}).get('predicted_delay_hours','ERR')} h")
    time.sleep(step)

    # 2. INSPECTED — only CUSTOMS may fire this
    r = send({"container_id": cid, "event": "INSPECTED", "role": "CUSTOMS",
              "note": "Risk-based exam completed"})
    print(f"  INSPECTED        -> {r}")
    time.sleep(step)

    # 3. CLEARED — only PORT_AUTHORITY; auto-triggers PAYMENT_RELEASED
    r = send({"container_id": cid, "event": "CLEARED", "role": "PORT_AUTHORITY",
              "note": "Customs clearance granted"})
    print(f"  CLEARED          -> {r}  (payment auto-released by smart contract)")
    time.sleep(step)

    # 4. DISPATCHED — only TRANSPORTER
    r = send({"container_id": cid, "event": "DISPATCHED", "role": "TRANSPORTER",
              "note": "Exited VOC Port gate toward NH-138"})
    print(f"  DISPATCHED       -> {r}")
    return cid

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--fast", action="store_true", help="2s between stages")
    ap.add_argument("--step", type=int, default=6, help="seconds between stages")
    ap.add_argument("--containers", type=int, default=1)
    args = ap.parse_args()
    step = 2 if args.fast else args.step
    for _ in range(args.containers):
        journey(step)
        time.sleep(step)
    print("\nDone. Open http://localhost:5000 for the dashboard, "
          "or run: curl http://localhost:5000/api/verify")
