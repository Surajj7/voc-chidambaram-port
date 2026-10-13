# VOC Port Smart Container Tracker — Thoothukudi
### Smart Cities Mission & Sagarmala Digital Port Initiative

A transparent, intelligent port logistics platform for **V.O. Chidambaranar (VOC) Port, Thoothukudi, Tamil Nadu**.

Built to make port operations **smooth, efficient, and transparent** by integrating:
1. **Blockchain Immutability & Transparency:** An append-only SHA-256 hash-chained ledger where any data tamper is mathematically detected, paired with Ethereum smart contract rule enforcement (`contracts/ContainerTracker.sol`) and automated escrow settlement upon customs clearance.
2. **Machine Learning Delay Prediction & Proactive Mitigation:** A trained Random Forest pipeline (MAE 3.96h, $R^2 = 0.962$) calibrated to VOC Port throughput (~0.87M TEU, ~82% berth queue) that predicts container dwell hours and outputs tailored delay mitigation actions (Direct Port Delivery green channels, reefer cold-chain priority, and advance e-Sanchit customs filing).
3. **Categorized Operational Tracking:** Full visibility across **Yet to Arrive** (approaching vessels in Gulf of Mannar fairway), **In the Port** (berth discharge, customs scanning, central yard), and **What Has Left** (dispatched via Gate 1 onto NH-138 expressway).

---

## Architecture at a Glance

| Layer | Component | Functionality |
| :--- | :--- | :--- |
| **Operational Tracking** | `backend/core.py` & `dashboard.html` | Real-time categorization into **Yet to Arrive**, **In the Port**, and **What Has Left**, complete with a 6-stage lifecycle pipeline. |
| **Blockchain Transparency** | `backend/core.py` & `contracts/` | SHA-256 chained blocks (`{index, timestamp, data, prev_hash, hash}`). Tamper detection on `/api/verify` and automated escrow release on customs out-of-charge. |
| **ML Delay Optimization** | `ml/` (Random Forest, 300 estimators) | Evaluates trade flow, cargo type, terminal, berth saturation, and NE monsoon weather to predict dwell time and trigger delay mitigation strategies. |
| **IoT / Stakeholder Feed** | `iot_simulator/` | Simulates RFID berth sensors, customs officers, port authorities, and road transporters. |
| **Geospatial Tracking** | `backend/static/dashboard.html` | Interactive GIS radar map of Thoothukudi Harbour, outer anchorage, Berths VIII/IX, and NH-138 corridor. |

---

## Container Lifecycle & Categorization

```
[ CATEGORY: YET TO ARRIVE ]
  1. INBOUND       ──► Manifest & arrival notice filed by SHIPPING_LINE
                       ML delay prediction & mitigation strategy generated
                       Logged as SHA-256 Blockchain Block

[ CATEGORY: IN THE PORT ]
  2. ARRIVED       ──► Berth sensor (SYSTEM role) logs vessel docking at Berth VIII/IX
  3. INSPECTED     ──► Customs Commissionerate signs off physical / gamma scanner exam
  4. CLEARED       ──► VOC Port Authority issues out-of-charge clearance
                       └─► AUTOMATIC: PAYMENT_RELEASED (SMART CONTRACT)
                           Escrow payment released autonomously without manual delay

[ CATEGORY: WHAT HAS LEFT ]
  5. DISPATCHED    ──► Road TRANSPORTER collects container; Gate 1 pass issued
  6. DEPARTED      ──► Outer RFID sensor records highway exit onto NH-138 corridor
```

---

## Quick Start (3 Steps)

### 1. Launch HTTP Backend & Dashboard
```bash
python backend/app.py
```
*Runs on the Python standard library with zero web framework dependencies. Serves the command dashboard on `http://localhost:5000`.*

### 2. (Optional) Run the IoT Simulator
In a separate terminal:
```bash
# Walk a container through the complete 6-stage lifecycle (~12s)
python iot_simulator/simulate.py --fast

# Or re-seed the full 12-container fleet
python iot_simulator/seed_demo.py
```

### 3. Open the Command Dashboard
Visit [http://localhost:5000](http://localhost:5000) in your web browser.

---

## Interactive Dashboard Features

1. **Executive KPI Ribbon:** Live counters for Yet to Arrive, Inside VOC Port, What Has Left, average predicted dwell time, hours saved by delay mitigation AI, and blockchain block count.
2. **Category Tabs & Filters:** Switch instantly between *All Containers*, *Yet to Arrive*, *In the Port*, and *What Has Left*, with instant search by container code, cargo, or shipping line.
3. **ML Dwell Prediction & Mitigation Badges:** View predicted dwell hours and proactive interventions (e.g. *Direct Port Delivery Green Channel*, *Reefer Cold-Chain Express*, *Advance e-Sanchit Scrutiny*).
4. **Thoothukudi Harbour GIS Map:** Interactive Leaflet radar map tracking ships in the outer anchorage, berths in the inner harbour, and trucks on NH-138.
5. **Blockchain Explorer & Hacker-Tamper Test:**
   - Click **Verify Chain** to recompute every SHA-256 block hash.
   - Click **Run Hacker-Tamper Test** to simulate an unauthorized database edit; watch the dashboard instantly detect the cryptographic breach at the exact block index!
   - Click **Smart Contract Rules** to view Solidity rules and automated escrow logic.
6. **ML Delay Optimizer Lab:** Adjust berth queue utilization (55%–99%), toggle customs exam, select cargo types and monsoon months, and watch predicted turnaround dwell times update in real time.

---

## Project Layout

```
voc-port-smart-tracker/
├── backend/
│   ├── app.py             # Stdlib HTTP server & REST API (port 5000)
│   ├── core.py            # Append-only ledger, role gating, ML prediction, state machine
│   └── static/
│       └── dashboard.html # High-fidelity Smart Port Command Center UI (Leaflet GIS)
├── contracts/
│   ├── ContainerTracker.sol # Solidity smart contract matching core.py rules
│   └── HARDHAT.md         # Deployment instructions for Sepolia testnet
├── data/
│   └── voc_port_dwell_dataset.csv # 5,000-row synthetic calibrated dataset
├── iot_simulator/
│   ├── seed_demo.py       # Seeds 12 containers across all 3 categories
│   └── simulate.py        # Plays real-time 6-stage lifecycle event journeys
├── ml/
│   ├── generate_dataset.py # Generates VOC-calibrated dwell dataset
│   ├── train_model.py     # Trains Random Forest pipeline (MAE 3.96h, R2 0.962)
│   └── model/             # Serialized joblib pipeline & feature specification
└── runtime/
    ├── ledger.json        # Append-only SHA-256 blockchain ledger
    └── state.json         # Current port inventory & shipment state
```
