"""Seed the VOC Port tracker with a realistic mix of containers.

Creates N containers (default 8) owned by real shipping lines, each frozen
at a different lifecycle stage, so the dashboard shows variety the moment
it loads: some boxes just arrived (with ML predictions), some in customs
exam, some cleared with payment auto-released, some already dispatched.

Usage:
    python iot_simulator/seed_demo.py              # 8 containers
    python iot_simulator/seed_demo.py -n 12 --fast
"""
import argparse
import json
import random
import time
import urllib.request

BASE = "http://localhost:5000"

OWNERS = ["Maersk Line", "MSC", "CMA CGM", "Ocean Network Express",
          "ZIM Shipping", "COSCO Shipping", "Hapag-Lloyd", "Evergreen Marine"]
VESSELS = ["MV Coromandel Trader", "MV Gulf Pearl", "MV Tamil Nadu Star",
           "MV Palk Strait", "MV Manapad Point", "MV Pearl City"]
CARGOES = [("Seafood", "Reefer"), ("Granite", "Dry"), ("Salt", "Dry"),
           ("Sugar", "Dry"), ("Textiles", "Dry"), ("Coal", "Dry"),
           ("Machinery", "ODC"), ("Electronics", "Dry"),
           ("Chemicals", "Hazardous"), ("Timber", "Dry")]
# final statuses to aim for, weighted toward early stages so the board looks alive
TARGETS = (["ARRIVED"] * 3 + ["INSPECTED"] * 3 +
           ["PAYMENT_RELEASED"] * 2 + ["DISPATCHED"] * 2)

def send(payload):
    req = urllib.request.Request(
        BASE + "/api/event", data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read())

def cid():
    return "TUTU" + "".join(random.choice("0123456789") for _ in range(7))

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", "--count", type=int, default=8)
    ap.add_argument("--fast", action="store_true")
    args = ap.parse_args()
    pause = 0.2 if args.fast else 1.0

    for i in range(args.count):
        c, owner = cid(), random.choice(OWNERS)
        cat, ctype = random.choice(CARGOES)
        details = {"vessel": random.choice(VESSELS),
                   "terminal": random.choice(["PSA_SICAL", "DBGT"]),
                   "trade": "Export" if cat in ("Seafood", "Granite", "Salt",
                                    "Sugar", "Textiles") and random.random() < .8
                            else "Import",
                   "cargo_category": cat, "cargo_type": ctype,
                   "arrival_date": time.strftime("%Y-%m-%d"),
                   "owner": owner, "berth": f"Inner Harbour Berth {random.choice(['V','IX','X'])}"}
        target = random.choice(TARGETS)
        try:
            r = send({"container_id": c, "event": "ARRIVED", "role": "SYSTEM",
                      "details": details})
            pred = r.get("prediction", {}).get("predicted_delay_hours", "?")
            if target == "ARRIVED":
                print(f"[{i+1}] {c}  {owner:22s} {cat:11s} stays ARRIVED  (ML: {pred} h)")
                continue
            time.sleep(pause)
            send({"container_id": c, "event": "INSPECTED", "role": "CUSTOMS",
                  "note": "Risk-based exam completed"})
            if target == "INSPECTED":
                print(f"[{i+1}] {c}  {owner:22s} {cat:11s} stays INSPECTED (ML: {pred} h)")
                continue
            time.sleep(pause)
            send({"container_id": c, "event": "CLEARED", "role": "PORT_AUTHORITY",
                  "note": "Customs clearance granted"})
            if target == "PAYMENT_RELEASED":
                print(f"[{i+1}] {c}  {owner:22s} {cat:11s} CLEARED -> payment auto-released (ML: {pred} h)")
                continue
            time.sleep(pause)
            send({"container_id": c, "event": "DISPATCHED", "role": "TRANSPORTER",
                  "note": "Exited VOC Port gate toward NH-138"})
            print(f"[{i+1}] {c}  {owner:22s} {cat:11s} fully DISPATCHED  (ML: {pred} h)")
        except Exception as e:
            print(f"[{i+1}] {c} failed: {e}")

    print("\nSeed complete. Open http://localhost:5000")
