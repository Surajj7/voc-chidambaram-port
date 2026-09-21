"""Train the container delay-prediction model (Random Forest) on the
generated VOC Port dataset. Saves a full sklearn Pipeline so the backend
can predict from raw categorical/numeric features without re-encoding.
"""
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "voc_port_dwell_dataset.csv"
MODEL_DIR = ROOT / "ml" / "model"
MODEL_DIR.mkdir(parents=True, exist_ok=True)

CATEGORICAL = ["trade", "cargo_category", "cargo_type", "terminal"]
NUMERIC = ["month", "day_of_week", "is_weekend", "is_holiday",
           "is_monsoon", "customs_exam", "vessel_queue"]
TARGET = "dwell_hours"

def main():
    df = pd.read_csv(DATA)
    X, y = df[CATEGORICAL + NUMERIC], df[TARGET]
    X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=0.2, random_state=42)

    pre = ColumnTransformer([
        ("cat", OneHotEncoder(handle_unknown="ignore"), CATEGORICAL),
        ("num", "passthrough", NUMERIC),
    ])
    model = Pipeline([
        ("pre", pre),
        ("rf", RandomForestRegressor(n_estimators=300, max_depth=14,
                                     random_state=42, n_jobs=-1)),
    ]).fit(X_tr, y_tr)

    pred = model.predict(X_te)
    mae = mean_absolute_error(y_te, pred)
    rmse = float(np.sqrt(mean_squared_error(y_te, pred)))
    r2 = r2_score(y_te, pred)
    print(f"Holdout metrics -> MAE: {mae:.2f} h | RMSE: {rmse:.2f} h | R2: {r2:.3f}")

    joblib.dump(model, MODEL_DIR / "delay_model.joblib")
    (MODEL_DIR / "feature_spec.json").write_text(json.dumps(
        {"categorical": CATEGORICAL, "numeric": NUMERIC}, indent=2))
    print(f"Saved model -> {MODEL_DIR / 'delay_model.joblib'}")

    # Feature importances for the report/viva
    rf = model.named_steps["rf"]
    names = model.named_steps["pre"].get_feature_names_out()
    imp = sorted(zip(names, rf.feature_importances_), key=lambda t: -t[1])[:10]
    print("Top-10 feature importances:")
    for n, v in imp:
        print(f"  {n:35s} {v:.3f}")

if __name__ == "__main__":
    main()
