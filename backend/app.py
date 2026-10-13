"""VOC Port Smart Container Tracker - HTTP backend.

Smart Cities Mission & Sagarmala Digital Port Initiative — Thoothukudi.
Pure-Python HTTP Server (zero third-party web framework dependencies):
    python backend/app.py -> http://localhost:5000

Endpoints:
  GET  /                  dashboard (Modern Command Center UI)
  GET  /api/state         shipments, operational categories, predictions, summary KPIs, ledger
  POST /api/event         IoT / stakeholder events {container_id, event, role, details, note}
  POST /api/seed          seed realistic fleet across Yet to Arrive, In Port, Departed
  GET  /api/health        model loaded? + holdout metrics + system diagnostics
  POST /api/predict       predict dwell hours & delay mitigation from features
  GET  /api/demo-tamper   forge a simulated block, prove mathematical detection
  GET  /api/verify        recompute full SHA-256 hash chain -> tamper check
  POST /api/reset         wipe demo state, re-create genesis block
"""
import copy
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from core import (
    Ledger, load_state, save_state, process_event, reset,
    predict_from_features, _load_model, seed_demo_fleet,
    CATEGORY_YET_TO_ARRIVE, CATEGORY_IN_PORT, CATEGORY_DEPARTED,
    get_category_bucket, assess_delay_mitigation
)

HERE = Path(__file__).resolve().parent
ROOT_ML = HERE.parent / "ml"
STATIC_DIR = HERE / "static"

LOCK = threading.Lock()
LEDGER = Ledger()
STATE = load_state()

# Auto-seed if state is currently empty so the dashboard has rich data on first load
if not STATE.get("shipments"):
    seed_demo_fleet(STATE, LEDGER)

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        # Quiet console for clean log output
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(n) or b"{}")

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        global LEDGER
        clean_path = self.path.split("?")[0]

        if clean_path in ("/", "/index.html", "/dashboard"):
            dashboard_path = STATIC_DIR / "dashboard.html"
            content = dashboard_path.read_text(encoding="utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(content.encode("utf-8"))

        elif clean_path == "/api/state":
            ok, bad = LEDGER.verify()
            with LOCK:
                shipments = list(STATE["shipments"].values())
                # Enrich any legacy shipments
                for s in shipments:
                    if not s.get("category_bucket"):
                        s["category_bucket"] = get_category_bucket(s.get("status", "ARRIVED"))
                    if s.get("prediction") and not s["prediction"].get("mitigation"):
                        s["prediction"]["mitigation"] = assess_delay_mitigation(
                            s["prediction"].get("predicted_delay_hours", 30.0), s.get("details", {})
                        )
                save_state(STATE)

            # Operational summaries
            yet_to_arrive = [s for s in shipments if s.get("category_bucket") == CATEGORY_YET_TO_ARRIVE]
            in_port = [s for s in shipments if s.get("category_bucket") == CATEGORY_IN_PORT]
            departed = [s for s in shipments if s.get("category_bucket") == CATEGORY_DEPARTED]

            dwell_times = [
                s.get("prediction", {}).get("predicted_delay_hours", 0)
                for s in shipments if s.get("prediction")
            ]
            avg_dwell = round(sum(dwell_times) / max(1, len(dwell_times)), 1)

            high_risks = [
                s for s in shipments
                if s.get("prediction", {}).get("mitigation", {}).get("risk_level") == "HIGH"
            ]

            saved_hours = sum(
                s.get("prediction", {}).get("mitigation", {}).get("estimated_hours_saved", 0)
                for s in shipments
            )

            sla_on_track = [
                s for s in shipments
                if s.get("prediction", {}).get("predicted_delay_hours", 0) <= 36.0
            ]
            sla_pct = round((len(sla_on_track) / max(1, len(shipments))) * 100, 1)

            summary = {
                "total": len(shipments),
                "yet_to_arrive": len(yet_to_arrive),
                "in_port": len(in_port),
                "departed": len(departed),
                "avg_dwell_hours": avg_dwell,
                "high_risk_count": len(high_risks),
                "hours_saved_ai": round(saved_hours, 1),
                "sla_compliance_pct": sla_pct,
            }

            self._json({
                "shipments": shipments,
                "summary": summary,
                "ledger_ok": ok,
                "ledger_blocks": len(LEDGER.chain),
                "ledger_tail": LEDGER.chain[-20:],
            })

        elif clean_path == "/api/health":
            try:
                _load_model()
                model_ok = True
            except Exception:
                model_ok = False

            metrics_path = ROOT_ML / "model" / "metrics.json"
            metrics = (json.loads(metrics_path.read_text(encoding="utf-8"))
                       if metrics_path.exists() else {})

            self._json({
                "model_loaded": model_ok,
                "metrics": metrics,
                "ledger_blocks": len(LEDGER.chain),
                "active_containers": len(STATE.get("shipments", {})),
            })

        elif clean_path == "/api/demo-tamper":
            # Demonstrates cryptographic tamper detection by forging a copy of a block
            tmp = Ledger.__new__(Ledger)
            tmp.chain = copy.deepcopy(LEDGER.chain)
            if len(tmp.chain) < 2:
                self._json({"error": "Need at least 2 blocks to demonstrate tamper"}, 400)
                return

            i = max(1, len(tmp.chain) // 2)
            orig_data = copy.deepcopy(tmp.chain[i]["data"])
            event_name = orig_data.get("event", "UNKNOWN")
            orig_hash = tmp.chain[i]["hash"]

            # Malicious edit simulation: hacker alters the event and note
            tmp.chain[i]["data"]["event"] = event_name + "_UNAUTHORIZED_TAMPER"
            tmp.chain[i]["data"]["note"] = "FRAUDULENT RECORD INSERTED BY UNAUTHORIZED PARTY"

            ok, bad = tmp.verify()
            self._json({
                "demo": True,
                "forged_block": i,
                "original_event": event_name,
                "original_hash": orig_hash,
                "tampered_data": tmp.chain[i]["data"],
                "detected": (not ok) and bad == i,
                "message": (
                    f"Simulated hacker modified block #{i} ('{event_name}'). "
                    f"Re-verification: {'TAMPER DETECTED at block #' + str(bad) + '! Cryptographic hash broke.' if not ok else 'FAILED to detect!'}"
                )
            })

        elif clean_path == "/api/verify":
            ok, bad = LEDGER.verify()
            self._json({
                "ok": ok,
                "tampered_block": bad,
                "blocks": len(LEDGER.chain)
            })

        else:
            self._json({"error": "Endpoint not found"}, 404)

    def do_POST(self):
        global LEDGER
        clean_path = self.path.split("?")[0]

        try:
            if clean_path == "/api/event":
                payload = self._body()
                with LOCK:
                    result = process_event(STATE, LEDGER, payload)
                    save_state(STATE)
                self._json(result)

            elif clean_path == "/api/seed":
                with LOCK:
                    result = seed_demo_fleet(STATE, LEDGER)
                self._json(result)

            elif clean_path == "/api/predict":
                row = self._body()
                needed = ["trade", "cargo_category", "cargo_type", "terminal",
                          "month", "day_of_week", "is_weekend", "is_holiday",
                          "is_monsoon", "customs_exam", "vessel_queue"]
                missing = [k for k in needed if k not in row]
                if missing:
                    raise ValueError(f"Missing required prediction features: {missing}")
                prediction_res = predict_from_features(row)
                self._json(prediction_res)

            elif clean_path == "/api/reset":
                with LOCK:
                    LEDGER = reset(STATE, LEDGER)
                self._json({"ok": True, "message": "Demo state wiped. Genesis block created."})

            else:
                self._json({"error": "Endpoint not found"}, 404)

        except ValueError as e:
            self._json({"ok": False, "error": str(e)}, 403)
        except Exception as e:
            self._json({"ok": False, "error": f"{type(e).__name__}: {e}"}, 400)


def _startup_check():
    try:
        _load_model()
        print("[OK] ML Delay Prediction Model loaded (ml/model/delay_model.joblib)")
    except Exception as e:
        print("[WARN] ML Model Warning:", e)

    ok, bad = LEDGER.verify()
    if ok:
        print(f"[OK] Blockchain Ledger intact: {len(LEDGER.chain)} blocks verified")
    else:
        print(f"[WARN] Blockchain Warning: Hash mismatch at block #{bad}")


if __name__ == "__main__":
    import sys
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    print("=" * 68)
    print("  VOC Port Smart Container Tracker - Thoothukudi")
    print("  Smart Cities Mission & Sagarmala Digital Port Initiative")
    print("  Dashboard URL: http://localhost:5000")
    print("=" * 68)
    _startup_check()
    ThreadingHTTPServer(("0.0.0.0", 5000), Handler).serve_forever()