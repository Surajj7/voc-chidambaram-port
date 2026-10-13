"""Core logic for the VOC Port Smart Container Tracker - Thoothukudi.

Smart Cities Mission & Sagarmala Digital Port Initiative.
Pure-Python, zero external service dependency for core operations.

Features:
  * 3 OPERATIONAL CATEGORIES:
      - YET TO ARRIVE (Inbound / Approaching Vessels / Manifest Logged)
      - IN THE PORT (Berth Docked / Customs Scan / Cleared & Auto-Escrow)
      - WHAT HAS LEFT (Dispatched / Exited Gate 1 onto NH-138)
  * STATUS FLOW:
      INBOUND -> ARRIVED -> INSPECTED -> CLEARED ->(auto) PAYMENT_RELEASED
      -> DISPATCHED -> DEPARTED
  * ROLE GATING (Smart Contract parity):
      - SHIPPING_LINE: Logs Inbound Notice & Manifest
      - SYSTEM: IoT Berth Sensor & Gate RFID Scanner (Arrived / Departed)
      - CUSTOMS: Customs Commissionerate Tuticorin (Inspected)
      - PORT_AUTHORITY: VOC Port Authority Clearance (Cleared)
      - SMART CONTRACT: Automated Escrow Payment Release
      - TRANSPORTER: Road Transporter Logistics Fleet (Dispatched)
  * BLOCKCHAIN LEDGER:
      Append-only SHA-256 hash-chained blocks. Every block stores prev_hash,
      actor signature, timestamp, event, and payload. Any tamper breaks the chain.
  * ML DWELL & DELAY PREDICTION:
      Random Forest trained on VOC Port historical operations.
      Predicts dwell hours, flags delay risk, and outputs proactive delay
      mitigation recommendations to prevent bottlenecks.
"""
from __future__ import annotations

import copy
import hashlib
import json
import random
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODEL_PATH = ROOT / "ml" / "model" / "delay_model.joblib"
LEDGER_PATH = ROOT / "runtime" / "ledger.json"
STATE_PATH = ROOT / "runtime" / "state.json"

# ---------------------------------------------------------------- statuses
INBOUND = "INBOUND"
ARRIVED = "ARRIVED"
INSPECTED = "INSPECTED"
CLEARED = "CLEARED"
PAYMENT_RELEASED = "PAYMENT_RELEASED"
DISPATCHED = "DISPATCHED"
DEPARTED = "DEPARTED"

FLOW = [INBOUND, ARRIVED, INSPECTED, CLEARED, PAYMENT_RELEASED, DISPATCHED, DEPARTED]

# Category Buckets as requested: Yet to arrive, In Port, What has left
CATEGORY_YET_TO_ARRIVE = "YET_TO_ARRIVE"
CATEGORY_IN_PORT = "IN_PORT"
CATEGORY_DEPARTED = "DEPARTED"

def get_category_bucket(status: str) -> str:
    """Categorizes container into the 3 operational states."""
    if status in (INBOUND, "EXPECTED", "SCHEDULED", "YET_TO_ARRIVE"):
        return CATEGORY_YET_TO_ARRIVE
    elif status in (ARRIVED, INSPECTED, CLEARED, PAYMENT_RELEASED):
        return CATEGORY_IN_PORT
    elif status in (DISPATCHED, DEPARTED):
        return CATEGORY_DEPARTED
    return CATEGORY_IN_PORT

# Role-based access control (mirrors contracts/ContainerTracker.sol)
TRANSITION_ROLES = {
    INBOUND: "SHIPPING_LINE",
    ARRIVED: "SYSTEM",
    INSPECTED: "CUSTOMS",
    CLEARED: "PORT_AUTHORITY",
    DISPATCHED: "TRANSPORTER",
    DEPARTED: "SYSTEM",
}

ACTOR_LABELS = {
    "SYSTEM": "IoT Gate / Berth Sensor",
    "SHIPPING_LINE": "Shipping Line Agent",
    "CUSTOMS": "Customs (Tuticorin Commissionerate)",
    "PORT_AUTHORITY": "VOC Port Authority",
    "TRANSPORTER": "Road Transporter / Logistics Fleet",
    "SMART_CONTRACT": "Smart Contract (Automated Escrow)",
}

# Real coordinates across V.O. Chidambaranar Port, Thoothukudi
ZONE_COORDINATES = {
    INBOUND: {"lat": 8.4892, "lng": 78.1885, "zone": "Outer Anchorage (Gulf of Mannar Fairway Approach)"},
    ARRIVED: {"lat": 8.4718, "lng": 78.1259, "zone": "Container Berth IX (PSA SICAL Terminal)"},
    INSPECTED: {"lat": 8.4735, "lng": 78.1180, "zone": "Tuticorin Customs Inspection CFS & Scanner Shed"},
    CLEARED: {"lat": 8.4760, "lng": 78.1140, "zone": "Central Staging Yard - Ready for Outbound Dispatch"},
    PAYMENT_RELEASED: {"lat": 8.4760, "lng": 78.1140, "zone": "Central Staging Yard - Escrow Released"},
    DISPATCHED: {"lat": 8.4820, "lng": 78.1070, "zone": "VOC Port Gate 1 Exit Corridor Plaza"},
    DEPARTED: {"lat": 8.4965, "lng": 78.0860, "zone": "NH-138 Expressway Corridor (Madurai/Hinterland En Route)"},
}

# ------------------------------------------------------------- hash chain
def _hash(block: dict) -> str:
    payload = json.dumps({k: v for k, v in block.items() if k != "hash"},
                         sort_keys=True).encode()
    return hashlib.sha256(payload).hexdigest()

class Ledger:
    """Append-only, SHA-256 hash-chained ledger demonstrating blockchain immutability."""

    def __init__(self, path: Path = LEDGER_PATH):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            try:
                self.chain = json.loads(self.path.read_text(encoding="utf-8"))
            except Exception:
                self.chain = []
        else:
            self.chain = []

        if not self.chain:
            genesis = {
                "index": 0,
                "timestamp": time.time(),
                "prev_hash": "0" * 64,
                "data": {
                    "event": "GENESIS",
                    "actor": "Smart Port Genesis Protocol",
                    "note": "VOC Port Smart Container Tracker - Thoothukudi Blockchain Genesis Block",
                    "authority": "V.O. Chidambaranar Port Authority"
                }
            }
            genesis["hash"] = _hash(genesis)
            self.chain = [genesis]
            self._save()

    def _save(self):
        self.path.write_text(json.dumps(self.chain, indent=2), encoding="utf-8")

    def append(self, data: dict) -> dict:
        prev = self.chain[-1]
        block = {
            "index": len(self.chain),
            "timestamp": time.time(),
            "prev_hash": prev["hash"],
            "data": data
        }
        block["hash"] = _hash(block)
        self.chain.append(block)
        self._save()
        return block

    def verify(self):
        """Recompute every SHA-256 hash and verify unbroken chain linkage.
        Returns (ok, first_bad_index).
        """
        for i, block in enumerate(self.chain):
            if block["hash"] != _hash(block):
                return False, i
            if i > 0 and block.get("prev_hash") != self.chain[i - 1]["hash"]:
                return False, i
        return True, None

# --------------------------------------------------------------- ML layer
_model = None

def _load_model():
    global _model
    if _model is None:
        import joblib
        _model = joblib.load(MODEL_PATH)
    return _model

INDIAN_HOLIDAYS = {
    "01-26", "03-25", "04-14", "05-01", "08-15", "10-02",
    "12-25", "01-01", "04-18", "11-08",
}

def predict_delay(details: dict, container_id: str) -> dict:
    """Predict clearance dwell time (hours) for a container using the trained Random Forest.
    Calculates operational risk rating and proactive delay mitigation recommendations.
    """
    model = _load_model()
    arr_date = details.get("arrival_date") or time.strftime("%Y-%m-%d")
    try:
        y, m, d = (int(x) for x in arr_date.split("-"))
        dt = date(y, m, d)
    except Exception:
        dt = date.today()

    jitter = ((sum(ord(c) for c in container_id) % 7) - 3) * 0.01
    row = {
        "trade": details.get("trade", "Export"),
        "cargo_category": details.get("cargo_category", "Seafood"),
        "cargo_type": details.get("cargo_type", "Reefer"),
        "terminal": details.get("terminal", "PSA_SICAL"),
        "month": dt.month,
        "day_of_week": dt.weekday(),
        "is_weekend": 1 if dt.weekday() >= 5 else 0,
        "is_holiday": 1 if f"{dt.month:02d}-{dt.day:02d}" in INDIAN_HOLIDAYS else 0,
        "is_monsoon": 1 if dt.month in (10, 11, 12) else 0,
        "customs_exam": 0.18,          # historical base rate (unknown at arrival)
        "vessel_queue": round(min(0.99, max(0.55, 0.82 + jitter)), 3),
    }

    import pandas as pd
    pred = float(model.predict(pd.DataFrame([row]))[0])
    pred_h = round(pred, 1)

    mitigation = assess_delay_mitigation(pred_h, details)
    return {
        "predicted_delay_hours": pred_h,
        "features_used": row,
        "mitigation": mitigation,
    }

def assess_delay_mitigation(pred_hours: float, details: dict) -> dict:
    """Evaluates ML predicted dwell time and determines proactive smart port interventions
    to ensure minimal delay and maintain port SLA (< 36 hours).
    """
    cargo_cat = details.get("cargo_category", "")
    cargo_type = details.get("cargo_type", "")
    trade = details.get("trade", "Export")
    terminal = details.get("terminal", "PSA_SICAL")

    sla_benchmark = 36.0  # VOC Port standard turnaround target

    if pred_hours <= 32.0:
        risk = "LOW"
        risk_label = "Low Delay Risk"
        badge_color = "success"
        strategy = "Direct Port Delivery (DPD) Green Channel"
        action = "Eligible for immediate green channel evacuation upon quay discharge; bypasses CFS storage buffer."
        saved_hours = 14.0
    elif pred_hours <= 52.0:
        risk = "MEDIUM"
        risk_label = "Moderate Delay Risk"
        badge_color = "warning"
        strategy = "Dynamic Yard Staging & e-Sanchit Pre-Scrutiny"
        action = f"Pre-allocate Terminal {terminal} Quick-Turnaround block; notify transporter for night gate dispatch."
        saved_hours = 18.5
    else:
        risk = "HIGH"
        risk_label = "High Delay Risk"
        badge_color = "danger"
        strategy = "Expedited Port Authority Clearance Escalation"
        action = "Flagged to Tuticorin Customs Commissionerate for priority scanning queue; dedicated RTG crane reserved."
        saved_hours = 28.0

    # Cargo-specific smart port intelligence
    if cargo_cat == "Seafood" or cargo_type == "Reefer":
        strategy = "⚡ Reefer Cold-Chain Integrity Fast-Track"
        action = "Perishable seafood export prioritized. Dedicated shore power plug point guaranteed with zero turnaround wait."
        saved_hours = max(saved_hours, 22.0)
    elif cargo_type == "Hazardous" or cargo_cat == "Chemicals":
        strategy = "🛡 Hazmat Segregated Green Lane"
        action = "Pre-designated safety buffer in yard; direct transfer onto bonded tanker truck."
    elif cargo_type == "ODC" or cargo_cat == "Machinery":
        strategy = "🚜 Heavy Lift Pre-Staging"
        action = "Mobile harbour crane pre-positioned at Berth V for seamless oversize offload."

    return {
        "risk_level": risk,
        "risk_label": risk_label,
        "badge_color": badge_color,
        "sla_benchmark_hours": sla_benchmark,
        "hours_diff_vs_sla": round(pred_hours - sla_benchmark, 1),
        "strategy": strategy,
        "action": action,
        "estimated_hours_saved": saved_hours,
    }

def predict_from_features(row: dict) -> dict:
    """Predict dwell hours and mitigation from arbitrary feature row (ML Lab panel)."""
    model = _load_model()
    import pandas as pd
    pred_h = round(float(model.predict(pd.DataFrame([row]))[0]), 1)
    mitigation = assess_delay_mitigation(pred_h, row)
    return {
        "predicted_delay_hours": pred_h,
        "mitigation": mitigation,
    }

# ------------------------------------------------------------ state machine
def process_event(state: dict, ledger: Ledger, payload: dict) -> dict:
    """Apply one event to a container. Enforces role-based permissions,
    blockchain SHA-256 recording, and state machine transitions.
    """
    event = payload["event"].upper()
    role = payload.get("role", "SYSTEM").upper()
    now = time.time()
    actor = ACTOR_LABELS.get(role, role)
    cid = payload["container_id"]

    # 1. New Inbound Manifest Notification (Yet to Arrive)
    if event == INBOUND:
        if cid in state["shipments"]:
            raise ValueError(f"Container {cid} already exists in the system.")
        details = payload.get("details", {})
        pred = predict_delay(details, cid)
        coords = ZONE_COORDINATES[INBOUND]
        state["shipments"][cid] = {
            "container_id": cid,
            "status": INBOUND,
            "category_bucket": CATEGORY_YET_TO_ARRIVE,
            "geo": coords,
            "history": [{
                "status": INBOUND,
                "actor": actor,
                "ts": now,
                "note": payload.get("note") or f"Inbound notice filed for vessel {details.get('vessel', 'En Route')}"
            }],
            "details": details,
            "prediction": pred,
        }
        ledger.append({
            "container_id": cid,
            "event": INBOUND,
            "actor": actor,
            "note": payload.get("note", "Manifest and advance arrival notification logged"),
            "details": details
        })
        return {"ok": True, "container": state["shipments"][cid], "prediction": pred}

    # 2. Berth Arrival (transition from INBOUND, or direct initial arrival)
    if event == ARRIVED:
        if cid not in state["shipments"]:
            # Direct arrival without prior inbound notice (backward-compatible)
            details = payload.get("details", {})
            pred = predict_delay(details, cid)
            coords = ZONE_COORDINATES[ARRIVED]
            state["shipments"][cid] = {
                "container_id": cid,
                "status": ARRIVED,
                "category_bucket": CATEGORY_IN_PORT,
                "geo": coords,
                "history": [{
                    "status": ARRIVED,
                    "actor": actor,
                    "ts": now,
                    "note": payload.get("note") or f"Berth arrival: {details.get('vessel', 'Docked')}"
                }],
                "details": details,
                "prediction": pred,
            }
            ledger.append({
                "container_id": cid,
                "event": ARRIVED,
                "actor": actor,
                "note": payload.get("note", "Docked at VOC Port container berth"),
                "details": details
            })
            return {"ok": True, "container": state["shipments"][cid], "prediction": pred}
        else:
            # Transition from INBOUND -> ARRIVED
            ship = state["shipments"][cid]
            if ship["status"] != INBOUND:
                raise ValueError(f"Cannot mark ARRIVED: container {cid} is already {ship['status']}.")
            ship["status"] = ARRIVED
            ship["category_bucket"] = CATEGORY_IN_PORT
            ship["geo"] = ZONE_COORDINATES[ARRIVED]
            note = payload.get("note") or f"Vessel docked; container unloaded at berth {ship['details'].get('berth', 'Berth IX')}"
            ship["history"].append({"status": ARRIVED, "actor": actor, "ts": now, "note": note})
            ledger.append({"container_id": cid, "event": ARRIVED, "actor": actor, "note": note})
            return {"ok": True, "status": ARRIVED, "container": ship}

    # Subsequent events require an existing container
    ship = state["shipments"].get(cid)
    if ship is None:
        raise ValueError(f"Unknown container {cid}. Must be registered via INBOUND or ARRIVED first.")

    cur = ship["status"]

    if event == PAYMENT_RELEASED:
        raise ValueError("PAYMENT_RELEASED is autonomous and fired by the Smart Contract upon CLEARED.")

    if event not in TRANSITION_ROLES:
        raise ValueError(f"Unknown lifecycle event: {event}.")

    # Role enforcement check
    required = TRANSITION_ROLES[event]
    if role != required:
        raise ValueError(f"ACCESS DENIED: '{event}' requires role '{required}', but actor is '{role}'.")

    # Workflow state machine sequence check
    expected_next = None
    if cur in FLOW:
        idx = FLOW.index(cur)
        if idx + 1 < len(FLOW):
            expected_next = FLOW[idx + 1]

    if event != expected_next:
        raise ValueError(f"Invalid workflow transition: cannot go from '{cur}' to '{event}' (expected '{expected_next}').")

    # Update container state
    ship["status"] = event
    ship["category_bucket"] = get_category_bucket(event)
    if event in ZONE_COORDINATES:
        ship["geo"] = ZONE_COORDINATES[event]

    note = payload.get("note", "")
    ship["history"].append({"status": event, "actor": actor, "ts": now, "note": note})
    ledger.append({"container_id": cid, "event": event, "actor": actor, "note": note})

    # SMART CONTRACT AUTOMATION:
    # Customs clearance automatically triggers payment release escrow settlement
    if event == CLEARED:
        auto_ts = time.time()
        auto_actor = ACTOR_LABELS["SMART_CONTRACT"]
        auto_note = "Smart contract condition verified: Customs clearance hash confirmed. Port dues settled & terminal pass issued."
        ship["status"] = PAYMENT_RELEASED
        ship["category_bucket"] = CATEGORY_IN_PORT
        ship["geo"] = ZONE_COORDINATES[PAYMENT_RELEASED]
        ship["history"].append({
            "status": PAYMENT_RELEASED,
            "actor": auto_actor,
            "ts": auto_ts,
            "note": auto_note
        })
        ledger.append({
            "container_id": cid,
            "event": PAYMENT_RELEASED,
            "actor": auto_actor,
            "note": auto_note
        })

    return {"ok": True, "status": ship["status"], "container": ship}

# ------------------------------------------------------------ persistence
def load_state() -> dict:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {"shipments": {}}
    return {"shipments": {}}

def save_state(state: dict):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")

def reset(state: dict, ledger: Ledger):
    state["shipments"] = {}
    save_state(state)
    fresh = Ledger.__new__(Ledger)
    fresh.path = ledger.path
    genesis = {
        "index": 0,
        "timestamp": time.time(),
        "prev_hash": "0" * 64,
        "data": {
            "event": "GENESIS",
            "actor": "Smart Port Genesis Protocol",
            "note": "VOC Port Smart Container Tracker - Thoothukudi Blockchain Genesis Block",
            "authority": "V.O. Chidambaranar Port Authority"
        }
    }
    genesis["hash"] = _hash(genesis)
    fresh.chain = [genesis]
    fresh._save()
    return fresh

# ------------------------------------------------------------ seed fleet
def seed_demo_fleet(state: dict, ledger: Ledger) -> dict:
    """Populates realistic demo containers across all 3 key categories:
       - YET TO ARRIVE (Inbound approaching vessels)
       - IN THE PORT (Active docked, customs exam, cleared)
       - WHAT HAS LEFT (Dispatched out of gate onto NH-138)
    """
    reset(state, ledger)

    OWNERS = [
        "Maersk Line", "MSC Mediterranean Shipping", "CMA CGM Group",
        "Ocean Network Express (ONE)", "Hapag-Lloyd", "Evergreen Marine",
        "ZIM Integrated Shipping", "Wan Hai Lines"
    ]
    VESSELS = [
        "MV Coromandel Trader", "MV Gulf Pearl", "MV Tamil Nadu Star",
        "MV Palk Strait", "MV Manapad Point", "MV Pearl City Express",
        "MV Tuticorin Pioneer"
    ]
    CARGO_SPECS = [
        ("Seafood", "Reefer", "Export", "Colombo (Transshipment)"),
        ("Salt", "Dry", "Export", "Port Klang"),
        ("Granite", "Dry", "Export", "Antwerp"),
        ("Textiles", "Dry", "Export", "Jebel Ali"),
        ("Sugar", "Dry", "Export", "Durban"),
        ("Machinery", "ODC", "Import", "Singapore"),
        ("Coal", "Dry", "Import", "Tanjung Pelepas"),
        ("Electronics", "Dry", "Import", "Busan"),
        ("Chemicals", "Hazardous", "Import", "Rotterdam"),
        ("Timber", "Dry", "Import", "Port Louis"),
        ("EdibleOil", "LiquidBulk", "Import", "Belawan"),
        ("Granite", "Dry", "Export", "Yokohama"),
    ]

    # Pre-planned distribution: 4 Yet to Arrive, 5 In Port, 3 Departed
    distributions = [
        # (Status, Target Category)
        (INBOUND, CATEGORY_YET_TO_ARRIVE),
        (INBOUND, CATEGORY_YET_TO_ARRIVE),
        (INBOUND, CATEGORY_YET_TO_ARRIVE),
        (INBOUND, CATEGORY_YET_TO_ARRIVE),
        (ARRIVED, CATEGORY_IN_PORT),
        (ARRIVED, CATEGORY_IN_PORT),
        (INSPECTED, CATEGORY_IN_PORT),
        (INSPECTED, CATEGORY_IN_PORT),
        (PAYMENT_RELEASED, CATEGORY_IN_PORT),
        (DISPATCHED, CATEGORY_DEPARTED),
        (DEPARTED, CATEGORY_DEPARTED),
        (DEPARTED, CATEGORY_DEPARTED),
    ]

    base_time = time.time() - 3600 * 24

    for i, (target_status, bucket) in enumerate(distributions):
        cid = f"TUTU{7000000 + i * 1423 + random.randint(10, 99)}"
        cargo_cat, cargo_type, trade, route_port = CARGO_SPECS[i % len(CARGO_SPECS)]
        owner = OWNERS[i % len(OWNERS)]
        vessel = VESSELS[i % len(VESSELS)]
        term = "PSA_SICAL" if i % 2 == 0 else "DBGT"
        berth = "Berth IX (PSA SICAL)" if term == "PSA_SICAL" else "Berth VIII (DBGT)"

        eta_offset = (i + 1) * 3
        eta_str = f"+{eta_offset}h (Approaching Outer Fairway)" if target_status == INBOUND else "Docked"

        details = {
            "vessel": vessel,
            "terminal": term,
            "trade": trade,
            "cargo_category": cargo_cat,
            "cargo_type": cargo_type,
            "owner": owner,
            "berth": berth,
            "arrival_date": time.strftime("%Y-%m-%d"),
            "eta": eta_str,
            "origin_destination": route_port,
            "teu": 1 if i % 3 != 0 else 2,
        }

        # 1. Start with INBOUND
        process_event(state, ledger, {
            "container_id": cid,
            "event": INBOUND,
            "role": "SHIPPING_LINE",
            "details": details,
            "note": f"Electronic Manifest & Cargo Declaration filed by {owner}"
        })

        if target_status == INBOUND:
            continue

        # 2. Advance to ARRIVED
        process_event(state, ledger, {
            "container_id": cid,
            "event": ARRIVED,
            "role": "SYSTEM",
            "note": f"RFID Berth sensor confirmed vessel {vessel} docked at {berth}"
        })

        if target_status == ARRIVED:
            continue

        # 3. Advance to INSPECTED
        process_event(state, ledger, {
            "container_id": cid,
            "event": INSPECTED,
            "role": "CUSTOMS",
            "note": "Customs Commissionerate physical inspection & gamma scanner verification passed"
        })

        if target_status == INSPECTED:
            continue

        # 4. Advance to CLEARED (automatically triggers PAYMENT_RELEASED)
        process_event(state, ledger, {
            "container_id": cid,
            "event": CLEARED,
            "role": "PORT_AUTHORITY",
            "note": "Customs out-of-charge issued. VOC Port Authority gate clearance granted"
        })

        if target_status in (CLEARED, PAYMENT_RELEASED):
            continue

        # 5. Advance to DISPATCHED
        process_event(state, ledger, {
            "container_id": cid,
            "event": DISPATCHED,
            "role": "TRANSPORTER",
            "note": "Commercial chassis loaded; Gate 1 RFID entry exit pass generated"
        })

        if target_status == DISPATCHED:
            continue

        # 6. Advance to DEPARTED
        process_event(state, ledger, {
            "container_id": cid,
            "event": DEPARTED,
            "role": "SYSTEM",
            "note": "Outbound RFID boom barrier opened; container en route via NH-138 Expressway"
        })

    save_state(state)
    return {
        "ok": True,
        "seeded_count": len(distributions),
        "total_containers": len(state["shipments"]),
        "blocks": len(ledger.chain)
    }
