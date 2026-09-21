"""Core logic for the VOC Port Smart Container Tracker.

Pure-Python, zero third-party dependencies. This module is deliberately
kept separate from the HTTP layer (app.py) so every rule can be unit-tested:

  * STATUS FLOW   — ARRIVED -> INSPECTED -> CLEARED ->(auto) PAYMENT_RELEASED
                    -> DISPATCHED
  * ROLE GATING   — only the authorised stakeholder can fire each manual
                    transition (mirrors the Solidity contract's onlyRole)
  * LEDGER        — append-only SHA-256 hash-chained blocks: any edit to a
                    stored block breaks the chain (mirrors blockchain
                    immutability, runs locally so the demo needs no testnet)
  * ML PREDICTION — at ARRIVAL the dwell/delay is predicted with the trained
                    Random Forest (loaded lazily from ml/model/)
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODEL_PATH = ROOT / "ml" / "model" / "delay_model.joblib"
LEDGER_PATH = ROOT / "runtime" / "ledger.json"
STATE_PATH = ROOT / "runtime" / "state.json"

# ---------------------------------------------------------------- statuses
ARRIVED, INSPECTED, CLEARED, PAYMENT_RELEASED, DISPATCHED = (
    "ARRIVED", "INSPECTED", "CLEARED", "PAYMENT_RELEASED", "DISPATCHED")
FLOW = [ARRIVED, INSPECTED, CLEARED, PAYMENT_RELEASED, DISPATCHED]

# who may fire each manual transition (mirrors onlyRole in the contract)
TRANSITION_ROLES = {
    INSPECTED: "CUSTOMS",
    CLEARED: "PORT_AUTHORITY",
    DISPATCHED: "TRANSPORTER",
}
ACTOR_LABELS = {
    "SYSTEM": "IoT Gate / Berth Sensor",
    "CUSTOMS": "Customs (Tuticorin Commissionerate)",
    "PORT_AUTHORITY": "VOC Port Authority",
    "TRANSPORTER": "Road Transporter",
}

# ------------------------------------------------------------- hash chain
def _hash(block: dict) -> str:
    payload = json.dumps({k: v for k, v in block.items() if k != "hash"},
                         sort_keys=True).encode()
    return hashlib.sha256(payload).hexdigest()

class Ledger:
    """Append-only, hash-chained event log (local stand-in for the chain)."""

    def __init__(self, path: Path = LEDGER_PATH):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            self.chain = json.loads(self.path.read_text(encoding="utf-8"))
        else:
            genesis = {"index": 0, "timestamp": time.time(),
                       "data": {"event": "GENESIS", "note": "VOC Port Smart "
                                "Container Tracker ledger - Thoothukudi"}}
            genesis["hash"] = _hash(genesis)
            self.chain = [genesis]
            self._save()

    def _save(self):
        self.path.write_text(json.dumps(self.chain, indent=1), encoding="utf-8")

    def append(self, data: dict) -> dict:
        prev = self.chain[-1]
        block = {"index": len(self.chain), "timestamp": time.time(),
                 "prev_hash": prev["hash"], "data": data}
        block["hash"] = _hash(block)
        self.chain.append(block)
        self._save()
        return block

    def verify(self):
        """Recompute every hash. Returns (ok, first_bad_index)."""
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
        import joblib  # imported lazily: backend runs even before training
        _model = joblib.load(MODEL_PATH)
    return _model

# A compact set of Indian gazetted holidays used to derive is_holiday from
# the arrival date (enough for a prototype; extend freely).
INDIAN_HOLIDAYS = {
    "01-26", "03-25", "04-14", "05-01", "08-15", "10-02",
    "12-25", "01-01", "04-18", "11-08",
}

def predict_delay(details: dict, container_id: str) -> dict:
    """Predict clearance delay (hours) for a newly arrived container.

    Features not yet known at arrival (customs_exam) are set to their
    historical base rates (docs/DATASET.md); vessel_queue uses VOC's ~82%
    utilisation with a per-container deterministic jitter.
    """
    from datetime import date
    model = _load_model()
    y, m, d = (int(x) for x in details["arrival_date"].split("-"))
    dt = date(y, m, d)
    jitter = ((sum(ord(c) for c in container_id) % 7) - 3) * 0.01
    row = {
        "trade": details["trade"],
        "cargo_category": details["cargo_category"],
        "cargo_type": details["cargo_type"],
        "terminal": details["terminal"],
        "month": dt.month,
        "day_of_week": dt.weekday(),
        "is_weekend": 1 if dt.weekday() >= 5 else 0,
        "is_holiday": 1 if f"{m:02d}-{d:02d}" in INDIAN_HOLIDAYS else 0,
        "is_monsoon": 1 if dt.month in (10, 11, 12) else 0,
        "customs_exam": 0.18,          # base rate (unknown at arrival)
        "vessel_queue": round(min(0.99, max(0.55, 0.82 + jitter)), 3),
    }
    import pandas as pd
    pred = float(model.predict(pd.DataFrame([row]))[0])
    return {"predicted_delay_hours": round(pred, 1), "features_used": row}

def predict_from_features(row: dict) -> float:
    """Predict dwell hours from an explicit feature row (ML test panel)."""
    model = _load_model()
    import pandas as pd
    return round(float(model.predict(pd.DataFrame([row]))[0]), 1)


# ------------------------------------------------------------ state machine
def process_event(state: dict, ledger: Ledger, payload: dict) -> dict:
    """Apply one event. Raises ValueError with a clear message on any rule
    violation (wrong role, bad transition, unknown container...)."""
    event = payload["event"].upper()
    role = payload.get("role", "SYSTEM").upper()
    now = time.time()
    actor = ACTOR_LABELS.get(role, role)

    if event == ARRIVED:
        cid = payload["container_id"]
        if cid in state["shipments"]:
            raise ValueError(f"{cid} already exists in the system.")
        details = payload.get("details", {})
        pred = predict_delay(details, cid)
        state["shipments"][cid] = {
            "container_id": cid,
            "status": ARRIVED,
            "history": [{"status": ARRIVED, "actor": actor, "ts": now,
                         "note": f"Berth arrival, {details.get('vessel','')}"}],
            "details": details,
            "prediction": pred,
        }
        ledger.append({"container_id": cid, "event": ARRIVED, "actor": actor,
                       "details": details})
        return {"ok": True, "prediction": pred}

    cid = payload["container_id"]
    ship = state["shipments"].get(cid)
    if ship is None:
        raise ValueError(f"Unknown container {cid}.")
    cur = ship["status"]

    if event == PAYMENT_RELEASED:
        raise ValueError("PAYMENT_RELEASED is automatic on CLEARED - "
                         "it cannot be fired manually.")
    if event not in TRANSITION_ROLES:
        raise ValueError(f"Unknown event {event}.")
    required = TRANSITION_ROLES[event]
    if role != required:
        raise ValueError(f"ACCESS DENIED: '{event}' requires role "
                         f"{required}, got {role}.")
    expected_next = FLOW[FLOW.index(cur) + 1] if cur in FLOW else None
    if event != expected_next:
        raise ValueError(f"Invalid transition {cur} -> {event}.")

    # fire the transition
    ship["status"] = event
    ship["history"].append({"status": event, "actor": actor, "ts": now,
                            "note": payload.get("note", "")})
    ledger.append({"container_id": cid, "event": event, "actor": actor,
                   "note": payload.get("note", "")})

    # AUTOMATION: clearance immediately triggers payment release
    if event == CLEARED:
        ship["status"] = PAYMENT_RELEASED
        ship["history"].append({"status": PAYMENT_RELEASED,
                                "actor": "SMART CONTRACT (auto)",
                                "ts": time.time(),
                                "note": "Auto-released on customs clearance"})
        ledger.append({"container_id": cid, "event": PAYMENT_RELEASED,
                       "actor": "SMART CONTRACT (auto)",
                       "note": "Auto-released on customs clearance"})

    return {"ok": True, "status": ship["status"]}

# ------------------------------------------------------------ persistence
def load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    return {"shipments": {}}

def save_state(state: dict):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=1), encoding="utf-8")

def reset(state: dict, ledger: Ledger):
    state["shipments"] = {}
    save_state(state)
    fresh = Ledger.__new__(Ledger)
    fresh.path, fresh.chain = ledger.path, [{
        "index": 0, "timestamp": time.time(),
        "data": {"event": "GENESIS", "note": "VOC Port Smart Container "
                 "Tracker ledger - Thoothukudi"}}]
    fresh.chain[0]["hash"] = _hash(fresh.chain[0])
    fresh._save()
    return fresh
