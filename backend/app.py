"""VOC Port Smart Container Tracker - HTTP backend.

Runs on the Python standard library ONLY (no pip install needed):
    python backend/app.py          -> http://localhost:5000

Endpoints
  GET  /                  dashboard
  GET  /api/state         shipments, statuses, predictions, ledger tail
  POST /api/event         IoT / stakeholder events
                          {container_id, event, role, details, note}
  GET  /api/health        model loaded? + holdout metrics
  POST /api/predict       predict dwell hours from a feature row (ML test panel)
  GET  /api/demo-tamper   forge a COPY of a block, prove detection
  GET  /api/verify        recompute the hash chain -> tamper check
  POST /api/reset         wipe demo state, re-create genesis block
"""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from core import (Ledger, load_state, save_state, process_event, reset,
                  predict_from_features, _load_model)

HERE = Path(__file__).resolve().parent
ROOT_ML = HERE.parent / "ml"
DASHBOARD = (HERE / "static" / "dashboard.html").read_text(encoding="utf-8")

LOCK = threading.Lock()
LEDGER = Ledger()
STATE = load_state()

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):        # quiet console
        pass

    # -- helpers ---------------------------------------------------------
    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(n) or b"{}")

    # -- routes ----------------------------------------------------------
    def do_GET(self):
        global LEDGER
        if self.path in ("/", "/index.html"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(DASHBOARD.encode())
        elif self.path == "/api/state":
            ok, bad = LEDGER.verify()
            with LOCK:
                save_state(STATE)
                shipments = list(STATE["shipments"].values())
            self._json({
                "shipments": shipments,
                "ledger_ok": ok,
                "ledger_blocks": len(LEDGER.chain),
                "ledger_tail": LEDGER.chain[-12:],
            })
        elif self.path == "/api/health":
            try:
                _load_model()
                model_ok = True
            except Exception:
                model_ok = False
            metrics_path = ROOT_ML / "model" / "metrics.json"
            metrics = (json.loads(metrics_path.read_text(encoding="utf-8"))
                       if metrics_path.exists() else {})
            self._json({"model_loaded": model_ok, "metrics": metrics})
        elif self.path == "/api/demo-tamper":
            # Prove the mechanics: tamper with a COPY of the chain, verify it.
            import copy
            tmp = Ledger.__new__(Ledger)
            tmp.chain = copy.deepcopy(LEDGER.chain)
            i = max(1, len(tmp.chain) // 2)
            ev = tmp.chain[i]["data"]["event"]
            tmp.chain[i]["data"]["event"] = ev + "*FORGED*"
            ok, bad = tmp.verify()
            self._json({"demo": True, "forged_block": i,
                        "original_event": ev,
                        "detected": (not ok) and bad == i,
                        "message": f"Simulated hacker edits block #{i} "
                                   f"('{ev}' -> '{ev}*FORGED*'). "
                                   f"Re-verification: {'TAMPER DETECTED at block #'+str(bad) if not ok else 'FAILED to detect!'}"})
        elif self.path == "/api/verify":
            ok, bad = LEDGER.verify()
            self._json({"ok": ok, "tampered_block": bad,
                        "blocks": len(LEDGER.chain)})
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self):
        global LEDGER
        try:
            if self.path == "/api/event":
                payload = self._body()
                with LOCK:
                    result = process_event(STATE, LEDGER, payload)
                    save_state(STATE)
                self._json(result)
            elif self.path == "/api/predict":
                row = self._body()
                needed = ["trade", "cargo_category", "cargo_type", "terminal",
                          "month", "day_of_week", "is_weekend", "is_holiday",
                          "is_monsoon", "customs_exam", "vessel_queue"]
                missing = [k for k in needed if k not in row]
                if missing:
                    raise ValueError(f"missing features: {missing}")
                self._json({"predicted_delay_hours": predict_from_features(row)})
            elif self.path == "/api/reset":
                with LOCK:
                    LEDGER = reset(STATE, LEDGER)
                self._json({"ok": True})
            else:
                self._json({"error": "not found"}, 404)
        except ValueError as e:
            self._json({"ok": False, "error": str(e)}, 403)
        except Exception as e:                       # noqa: BLE001
            self._json({"ok": False, "error": f"{type(e).__name__}: {e}"}, 400)

def _startup_model_check():
    try:
        _load_model()
        print("ML model: OK (ml/model/delay_model.joblib)")
    except ModuleNotFoundError as e:
        print("!" * 64)
        print("ML model could not be loaded - missing package:", e.name)
        print("Fix:  pip install -r requirements.txt")
        print("The dashboard will work, but predictions will fail until then.")
        print("!" * 64)
    except Exception as e:                       # noqa: BLE001
        print("ML model warning:", e)

if __name__ == "__main__":
    print("VOC Port Smart Container Tracker - Thoothukudi")
    print("Dashboard: http://localhost:5000")
    _startup_model_check()
    ThreadingHTTPServer(("0.0.0.0", 5000), Handler).serve_forever()