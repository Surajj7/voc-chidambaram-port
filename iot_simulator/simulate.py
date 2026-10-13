"""Simulated IoT / stakeholder event feed for VOC Port, Thoothukudi.

Smart Cities Mission & Sagarmala Digital Port Initiative.
Demonstrates the full end-to-end container lifecycle:
  1. INBOUND      (Role: SHIPPING_LINE) — Inbound notice / Manifest filed (Yet to Arrive)
  2. ARRIVED      (Role: SYSTEM)        — Vessel docked at berth; RFID scanned (In Port)
  3. INSPECTED    (Role: CUSTOMS)       — Risk-based physical/gamma inspection completed (In Port)
  4. CLEARED      (Role: PORT_AUTHORITY)— Out-of-charge approved (In Port)
     └─► AUTO: PAYMENT_RELEASED (SMART CONTRACT) — Automated escrow release
  5. DISPATCHED   (Role: TRANSPORTER)   — Loaded on road trailer, gate pass stamped (Left Port)
  6. DEPARTED     (Role: SYSTEM)        — Outer gate sensor clears container onto NH-138 (Left Port)

Usage:
    python iot_simulator/simulate.py                 # 1 container, full journey
    python iot_simulator/simulate.py --fast          # ~1.5s per step
    python iot_simulator/simulate.py --containers 3  # 3 container journeys
"""
import argparse
import json
import random
import time
import urllib.request

BASE = "http://localhost:5000"
VESSELS = ["MV Coromandel Trader", "MV Gulf Pearl", "MV Tamil Nadu Star",
           "MV Palk Strait", "MV Manapad Point", "MV Pearl City Express"]
EXPORTS = [("Seafood", "Reefer"), ("Granite", "Dry"), ("Salt", "Dry"),
           ("Sugar", "Dry"), ("Textiles", "Dry")]
IMPORTS = [("Coal", "Dry"), ("Machinery", "ODC"), ("Electronics", "Dry"),
           ("Chemicals", "Hazardous"), ("Timber", "Dry")]
OWNERS = ["Maersk Line", "MSC Mediterranean Shipping", "CMA CGM Group",
          "Ocean Network Express", "Hapag-Lloyd", "Evergreen Marine"]

def send(payload):
    req = urllib.request.Request(
        BASE + "/api/event", data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {"ok": False, "error": json.loads(e.read())["error"]}

def journey(step, cid=None):
    cid = cid or "TUTU" + "".join(random.choice("0123456789") for _ in range(7))
    trade = "Export" if random.random() < 0.55 else "Import"
    cat, ctype = random.choice(EXPORTS if trade == "Export" else IMPORTS)
    terminal = random.choice(["PSA_SICAL", "DBGT"])
    berth = "Berth IX (PSA SICAL)" if terminal == "PSA_SICAL" else "Berth VIII (DBGT)"
    vessel = random.choice(VESSELS)
    owner = random.choice(OWNERS)

    print(f"\n=======================================================")
    print(f"  Container: {cid} | Shipping Line: {owner}")
    print(f"  Cargo: {cat} ({ctype}) | Trade: {trade} | Vessel: {vessel}")
    print(f"=======================================================")

    # 1. INBOUND — Yet to Arrive: Manifest filed by Shipping Line
    r = send({
        "container_id": cid,
        "event": "INBOUND",
        "role": "SHIPPING_LINE",
        "details": {
            "vessel": vessel,
            "terminal": terminal,
            "trade": trade,
            "cargo_category": cat,
            "cargo_type": ctype,
            "owner": owner,
            "berth": berth,
            "arrival_date": time.strftime("%Y-%m-%d"),
            "eta": "+4h (Approaching Fairway)"
        },
        "note": f"Electronic Bill of Lading filed by {owner}"
    })
    pred = r.get("prediction", {}).get("predicted_delay_hours", "?")
    strat = r.get("prediction", {}).get("mitigation", {}).get("strategy", "Standard")
    print(f"  [1/6] INBOUND (Yet to Arrive)   -> ML Delay Prediction: {pred} h")
    print(f"        Proactive Delay Strategy: {strat}")
    time.sleep(step)

    # 2. ARRIVED — In Port: Vessel berths, IoT sensor triggers dock event
    r = send({
        "container_id": cid,
        "event": "ARRIVED",
        "role": "SYSTEM",
        "note": f"Quay crane offloaded container at {berth}"
    })
    print(f"  [2/6] ARRIVED (In Port)          -> Status: {r.get('status')}")
    time.sleep(step)

    # 3. INSPECTED — In Port: Only CUSTOMS can fire
    r = send({
        "container_id": cid,
        "event": "INSPECTED",
        "role": "CUSTOMS",
        "note": "Tuticorin Customs Commissionerate physical verification and seal verification passed"
    })
    print(f"  [3/6] INSPECTED (In Port)        -> Status: {r.get('status')}")
    time.sleep(step)

    # 4. CLEARED — In Port: Only PORT_AUTHORITY; smart contract automatically releases payment
    r = send({
        "container_id": cid,
        "event": "CLEARED",
        "role": "PORT_AUTHORITY",
        "note": "VOC Port Trust out-of-charge granted. Gate-out clearance sanctioned"
    })
    print(f"  [4/6] CLEARED (In Port)          -> Status: {r.get('status')} (Payment auto-released by smart contract)")
    time.sleep(step)

    # 5. DISPATCHED — Left Port: Only TRANSPORTER
    r = send({
        "container_id": cid,
        "event": "DISPATCHED",
        "role": "TRANSPORTER",
        "note": "Mounted on multi-axle trailer, loaded via Gate 1 corridor"
    })
    print(f"  [5/6] DISPATCHED (Left Port)     -> Status: {r.get('status')}")
    time.sleep(step)

    # 6. DEPARTED — Left Port: Passed outer RFID boundary onto NH-138
    r = send({
        "container_id": cid,
        "event": "DEPARTED",
        "role": "SYSTEM",
        "note": "RFID barrier confirmed exit; en route via NH-138 expressway"
    })
    print(f"  [6/6] DEPARTED (Left Port)       -> Status: {r.get('status')} [Journey Complete]")
    return cid

if __name__ == "__main__":
    import sys
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--fast", action="store_true", help="1.5s between stages")
    ap.add_argument("--step", type=int, default=4, help="seconds between stages")
    ap.add_argument("--containers", type=int, default=1)
    args = ap.parse_args()
    step = 1.5 if args.fast else args.step

    for i in range(args.containers):
        journey(step)
        if i + 1 < args.containers:
            time.sleep(step)

    print("\n[OK] Simulation run finished. View live updates at: http://localhost:5000")
