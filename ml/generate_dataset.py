"""Generate a synthetic-but-realistic container dwell-time dataset for
V.O. Chidambaranar (VOC) Port, Thoothukudi, Tamil Nadu.

Every parameter below is anchored to a real-world reference, documented in
docs/DATASET.md. The dataset is deliberately *plausible*, not *official*:
it is a teaching prototype, and the report must say so.

Output: data/voc_port_dwell_dataset.csv  (5,000 rows)
"""
import numpy as np
import pandas as pd
from pathlib import Path

rng = np.random.default_rng(42)
N = 5000
ROOT = Path(__file__).resolve().parent.parent

# ---- Real-life anchors (see docs/DATASET.md) --------------------------------
# VOC Port handled ~0.87 M TEU in FY2025-26 on ~1.02 M TEU capacity => ~80-85%
# utilisation. Terminal congestion scales non-linearly above ~80%.
UTILISATION = 0.82
# NE monsoon hits the Tamil Nadu coast Oct-Dec: swell, slower crane ops,
# occasional closure days. Thoothukudi sits squarely in this belt.
MONSOON_MONTHS = {10, 11, 12}
# Indian major ports observe ~10-13 gazetted holidays / year (~3% of days).
HOLIDAY_RATE = 0.03
# Customs examination (risk-based) hits roughly 15-20% of boxes and is the
# single biggest discretionary delay (typically +1-3 days).
EXAM_RATE = 0.18
# Reefer cargo (Thoothukudi's frozen seafood exports) gets priority plug and
# faster clearance to protect cold-chain integrity.
REEFER_PRIORITY_H = -14.0

EXPORT_CARGOES = [  # (category, cargo_type, base_clear_h, share)
    ("Seafood",        "Reefer",    26, 0.30),  # Thoothukudi signature export
    ("Granite",        "Dry",       34, 0.20),
    ("Salt",           "Dry",       28, 0.15),
    ("Sugar",          "Dry",       30, 0.10),
    ("Textiles",       "Dry",       32, 0.10),
    ("Machinery",      "ODC",       44, 0.08),
    ("Electronics",    "Dry",       30, 0.07),
]
IMPORT_CARGOES = [
    ("Coal",           "Dry",       62, 0.22),
    ("Timber",         "Dry",       58, 0.15),
    ("Machinery",      "ODC",       66, 0.15),
    ("Electronics",    "Dry",       52, 0.15),
    ("Chemicals",      "Hazardous", 70, 0.13),
    ("EdibleOil",      "LiquidBulk",64, 0.10),
    ("Seafood",        "Reefer",    48, 0.10),
]

rows = []
for i in range(N):
    trade = "Export" if rng.random() < 0.55 else "Import"   # VOC is export-leaning
    table = EXPORT_CARGOES if trade == "Export" else IMPORT_CARGOES
    cats, types, bases, shares = zip(*table)
    idx = rng.choice(len(cats), p=np.array(shares) / np.sum(shares))
    category, cargo_type, base_h = cats[idx], types[idx], bases[idx]

    month = int(rng.integers(1, 13))
    dow = int(rng.integers(0, 7))               # 0=Mon ... 6=Sun
    is_weekend = 1 if dow >= 5 else 0
    is_holiday = 1 if rng.random() < HOLIDAY_RATE else 0
    is_monsoon = 1 if month in MONSOON_MONTHS else 0
    customs_exam = 1 if rng.random() < EXAM_RATE else 0
    terminal = "PSA_SICAL" if rng.random() < 0.60 else "DBGT"
    vessel_queue = float(np.clip(UTILISATION + rng.normal(0, 0.05), 0.55, 0.99))

    dwell = base_h
    dwell += REEFER_PRIORITY_H if cargo_type == "Reefer" else 0
    dwell += 30.0 * customs_exam                      # exam: +~1.25 days
    dwell += 22.0 * is_holiday                        # port closed
    dwell +=  9.0 * is_weekend * rng.random()         # thin weekend staffing
    dwell *= (1.30 if is_monsoon else 1.0)            # NE monsoon slowdown
    # Congestion penalty kicks in hard above ~80% utilisation
    dwell += max(0.0, vessel_queue - 0.80) * 180.0
    dwell += rng.lognormal(mean=0.0, sigma=0.45) * 8  # operational noise
    dwell = float(np.clip(dwell, 6.0, 240.0))

    rows.append(dict(
        container_id=f"TUTU{rng.integers(1000000, 9999999)}",
        trade=trade, cargo_category=category, cargo_type=cargo_type,
        terminal=terminal, month=month, day_of_week=dow,
        is_weekend=is_weekend, is_holiday=is_holiday, is_monsoon=is_monsoon,
        customs_exam=customs_exam, vessel_queue=round(vessel_queue, 3),
        dwell_hours=round(dwell, 1),
    ))

df = pd.DataFrame(rows)
out = ROOT / "data" / "voc_port_dwell_dataset.csv"
df.to_csv(out, index=False)
print(f"Wrote {len(df)} rows -> {out}")
print(df["dwell_hours"].describe().round(1))
