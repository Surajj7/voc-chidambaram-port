# VOC Port Smart Container Tracker — Thoothukudi

A working prototype that answers one question: **can every party who touches a
container at V.O. Chidambaranar Port trust the same picture of it — and know
what's coming before it goes wrong?**

Three technologies, each covering a blind spot the others have:

| Layer                | What it does in this repo                                                                                                                                                                                             |
| -------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **IoT (simulated)**  | `iot_simulator/simulate.py` emits the raw events (arrival, inspection…) that in production would come from VOC Port's RFID gate system / berth sensors                                                                |
| **Blockchain**       | `backend/core.py` keeps an append-only **SHA-256 hash-chained ledger** (any edit breaks the chain); `contracts/ContainerTracker.sol` is the identical rule-set as a deployable smart contract (optional Sepolia path) |
| **Machine Learning** | `ml/` trains a Random Forest on a VOC-calibrated dataset to predict clearance delay at arrival                                                                                                                        |

## Quick start (3 commands)

```bash
# 1. Backend : Serves dashboard on :5000
python backend/app.py

# 2. IoT simulator (new terminal). Walks a container through its full journey
python iot_simulator/simulate.py --fast

# 3. Open the dashboard
#    http://localhost:5000
```

That's it — no `pip install` needed for the demo. (The ML model ships
pre-trained; to regenerate it: `pip install -r requirements.txt` then
`python ml/generate_dataset.py && python ml/train_model.py`.)

## How it works — one container's journey

```
simulate.py                 backend (core.py)                    dashboard
─────────────              ───────────────────                  ─────────
ARRIVED  ───────────────►  ├─► ML model → "predicted delay: 38h"
(role: SYSTEM)             └─► ledger block #1 (SHA-256 chained)
INSPECTED ──────────────►  role must be CUSTOMS, else ACCESS DENIED
                           ledger block #2
CLEARED   ──────────────►  role must be PORT_AUTHORITY
                           └─► AUTOMATIC: PAYMENT_RELEASED block #3
                               (nobody has to "notice" — the rule fires itself)
DISPATCHED ─────────────►  role must be TRANSPORTER
                           ledger block #4
```

- **Trust (blockchain layer):** every event is a block `{index, timestamp,
data, prev_hash, hash}`. `GET /api/verify` recomputes the chain — try
  editing `runtime/ledger.json` with any text editor and click
  _Verify chain integrity_ on the dashboard: **TAMPER DETECTED**.
- **Foresight (ML layer):** at ARRIVED the backend builds a feature row
  (cargo, terminal, monsoon, weekend, holiday, VOC's ~82% berth queue) and
  the trained Random Forest returns predicted clearance hours.
- **Real-time (IoT layer):** events arrive as JSON over HTTP; in production
  the identical payloads would come from RFID/GPS hardware. VOC Port already
  operates an RFID-based truck/personnel entry system, so this is a realistic
  upgrade path.

## Try these in the dashboard's _Manual Event Panel_

1. Fire `CLEARED` as `TRANSPORTER` → `ACCESS DENIED: 'CLEARED' requires role
PORT_AUTHORITY, got TRANSPORTER.` _(role enforcement)_
2. Fire `PAYMENT_RELEASED` as anyone → it is automatic on `CLEARED`, never
   manual. _(automation)_
3. Try to skip a stage (e.g. `DISPATCHED` before `CLEARED`) → invalid
   transition. _(state machine)_
4. Edit `runtime/ledger.json`, then _Verify chain integrity_ → tamper
   detected with the exact block number. _(immutability)_

## Project layout

```
backend/app.py             stdlib HTTP server + JSON API (no pip needed)
backend/core.py            ledger, role-gated state machine, ML prediction
backend/static/dashboard.html   live dashboard (Leaflet map of Thoothukudi harbour)
iot_simulator/simulate.py  plays the IoT + stakeholder event feed
ml/generate_dataset.py     VOC-calibrated synthetic dataset (see docs/DATASET.md)
ml/train_model.py          trains + evaluates the Random Forest, saves pipeline
ml/model/                  pre-trained pipeline (ships with the zip)
contracts/                 identical rule-set as a Solidity smart contract
data/                      generated dataset (5,000 rows)
runtime/                   created at run time: ledger.json + state.json
```

## Honest limitations (say these in the viva)

- IoT is **simulated** — payloads and cadence are realistic, but no real
  sensors are attached.
- The ML dataset is **synthetic, calibrated to published VOC Port figures**
  (docs/DATASET.md) — the pipeline is the deliverable, not the exact numbers.
- The local hash-chain is a **demonstration of immutability mechanics**; the
  production path is `contracts/ContainerTracker.sol` on a public testnet,
  where storage is distributed and independently verifiable.
