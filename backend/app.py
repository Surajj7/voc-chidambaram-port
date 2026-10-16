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
import random
import threading
import time as clock
from datetime import date, datetime, time as datetime_time, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from core import (
    Ledger, load_state, save_state, process_event, reset,
    predict_from_features, _load_model, seed_demo_fleet,
    CATEGORY_YET_TO_ARRIVE, CATEGORY_IN_PORT, CATEGORY_DEPARTED,
    get_category_bucket, assess_delay_mitigation
)

HERE = Path(__file__).resolve().parent
ROOT_ML = HERE.parent / "ml"
STATIC_DIR = HERE / "static"


def _pdf_escape(value):
    text = str(value).encode("ascii", "replace").decode("ascii")
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _build_pdf(lines):
    """Build a small text PDF without adding a runtime dependency."""
    wrapped = []
    for line in lines:
        text = str(line)
        while len(text) > 96:
            split_at = text.rfind(" ", 0, 96)
            split_at = split_at if split_at > 0 else 96
            wrapped.append(text[:split_at])
            text = "  " + text[split_at:].lstrip()
        wrapped.append(text)

    pages = [wrapped[index:index + 48] for index in range(0, len(wrapped), 48)] or [[]]
    objects = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        3: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    }
    page_ids = []
    for page_index, page_lines in enumerate(pages):
        page_id = 4 + page_index * 2
        content_id = page_id + 1
        page_ids.append(page_id)
        commands = ["BT", "/F1 9 Tf", "48 790 Td", "14 TL"]
        for line in page_lines:
            commands.append(f"({_pdf_escape(line)}) Tj T*")
        commands.append("ET")
        stream = "\n".join(commands).encode("ascii")
        objects[page_id] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 842] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {content_id} 0 R >>"
        ).encode("ascii")
        objects[content_id] = (
            f"<< /Length {len(stream)} >>\nstream\n".encode("ascii")
            + stream + b"\nendstream"
        )

    kids = " ".join(f"{page_id} 0 R" for page_id in page_ids)
    objects[2] = f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>".encode("ascii")
    pdf = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0] * (max(objects) + 1)
    for object_id in sorted(objects):
        offsets[object_id] = len(pdf)
        pdf.extend(f"{object_id} 0 obj\n".encode("ascii"))
        pdf.extend(objects[object_id])
        pdf.extend(b"\nendobj\n")
    xref_offset = len(pdf)
    pdf.extend(f"xref\n0 {len(offsets)}\n".encode("ascii"))
    pdf.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        pdf.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    pdf.extend(
        f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n".encode("ascii")
    )
    return bytes(pdf)


def _report_for_dates(start_date, end_date):
    start = datetime.combine(start_date, time.min).timestamp()
    end = datetime.combine(end_date + timedelta(days=1), time.min).timestamp()
    with LOCK:
        shipments = copy.deepcopy(list(STATE["shipments"].values()))

    report_shipments = []
    for shipment in shipments:
        history = shipment.get("history", [])
        matching = [
            event for event in history
            if start <= float(event.get("ts", 0)) < end
        ]
        if matching:
            report_shipments.append((shipment, matching))

    report_shipments.sort(
        key=lambda item: max(float(event.get("ts", 0)) for event in item[1]),
        reverse=True,
    )
    lines = [
        "VOC PORT - CONTAINER MOVEMENT REPORT",
        f"Reporting period: {start_date.isoformat()} to {end_date.isoformat()}",
        f"Generated: {datetime.now().astimezone().strftime('%Y-%m-%d %H:%M %Z')}",
        f"Containers with activity in period: {len(report_shipments)}",
        "",
        "A container is included when at least one recorded lifecycle event falls in the period.",
        "Arrival and departure values below are the recorded event times; blank means not recorded.",
        "",
    ]
    for shipment, matching in report_shipments:
        details = shipment.get("details", {})
        history = shipment.get("history", [])
        arrival = next((event for event in history if event.get("status") == "ARRIVED"), None)
        departure = next((event for event in reversed(history) if event.get("status") == "DEPARTED"), None)
        lines.extend([
            f"Container: {shipment.get('container_id', 'Unknown')}  |  Current status: {shipment.get('status', 'Unknown')}",
            f"Vessel: {details.get('vessel', 'Not recorded')}  |  Shipping line: {details.get('owner', 'Not recorded')}",
            f"Cargo: {details.get('cargo_category', 'Not recorded')} / {details.get('cargo_type', 'Not recorded')}  |  Trade: {details.get('trade', 'Not recorded')}",
            f"Origin / destination: {details.get('origin_destination', 'Not recorded')}  |  Terminal: {details.get('terminal', 'Not recorded')}",
            f"Port arrival: {datetime.fromtimestamp(float(arrival['ts'])).astimezone().strftime('%Y-%m-%d %H:%M') if arrival else 'Not recorded'}",
            f"Port departure: {datetime.fromtimestamp(float(departure['ts'])).astimezone().strftime('%Y-%m-%d %H:%M') if departure else 'Not recorded'}",
        ])
        prediction = shipment.get("prediction", {}).get("predicted_delay_hours")
        if prediction is not None:
            lines.append(f"Estimated dwell: {prediction} hours")
        lines.append("Recorded events in selected period:")
        for event in sorted(matching, key=lambda item: float(item.get("ts", 0))):
            event_time = datetime.fromtimestamp(float(event.get("ts", 0))).astimezone().strftime("%Y-%m-%d %H:%M")
            lines.append(f"  {event_time}  {event.get('status', 'UPDATE')}  {event.get('actor', '')}  {event.get('note', '')}")
        lines.append("-" * 72)
    if not report_shipments:
        lines.append("No recorded container activity was found in this date range.")
    return _build_pdf(lines)

LOCK = threading.Lock()
LEDGER = Ledger()
STATE = load_state()
LIVE_DEMO = False

NEXT_DEMO_EVENT = {
    "INBOUND": ("ARRIVED", "SYSTEM"),
    "ARRIVED": ("INSPECTED", "CUSTOMS"),
    "INSPECTED": ("CLEARED", "PORT_AUTHORITY"),
    "PAYMENT_RELEASED": ("DISPATCHED", "TRANSPORTER"),
    "DISPATCHED": ("DEPARTED", "SYSTEM"),
}


class LiveDemoFeed:
    """Advance persisted demo shipments so both dashboards have live events."""

    def __init__(self, interval=5, manifest_interval=60):
        self.interval = interval
        self.manifest_interval = manifest_interval
        self._stop = threading.Event()
        self._next_manifest = clock.monotonic() + 10
        self._thread = threading.Thread(target=self._run, name="live-demo-feed", daemon=True)

    def start(self):
        self._thread.start()

    def _new_manifest(self):
        trade = random.choice(("Import", "Export"))
        cargo, cargo_type = random.choice(
            [("Seafood", "Reefer"), ("Granite", "Dry"), ("Salt", "Dry")]
            if trade == "Export"
            else [("Machinery", "ODC"), ("Electronics", "Dry"), ("Chemicals", "Hazardous")]
        )
        terminal = random.choice(("PSA_SICAL", "DBGT"))
        berth = "Berth IX (PSA SICAL)" if terminal == "PSA_SICAL" else "Berth VIII (DBGT)"
        container_id = "TUTU" + "".join(random.choice("0123456789") for _ in range(7))
        while container_id in STATE["shipments"]:
            container_id = "TUTU" + "".join(random.choice("0123456789") for _ in range(7))
        details = {
            "vessel": random.choice(("MV Coromandel Trader", "MV Gulf Pearl", "MV Tamil Nadu Star", "MV Palk Strait")),
            "terminal": terminal,
            "trade": trade,
            "cargo_category": cargo,
            "cargo_type": cargo_type,
            "owner": random.choice(("Maersk Line", "MSC Mediterranean Shipping", "CMA CGM Group")),
            "berth": berth,
            "arrival_date": date.today().isoformat(),
            "eta": "+4h (Approaching Fairway)",
        }
        process_event(STATE, LEDGER, {
            "container_id": container_id,
            "event": "INBOUND",
            "role": "SHIPPING_LINE",
            "details": details,
            "note": "Demo IoT feed: electronic manifest received",
        })

    def _advance_one(self):
        with LOCK:
            if clock.monotonic() >= self._next_manifest:
                self._new_manifest()
                self._next_manifest = clock.monotonic() + self.manifest_interval
                save_state(STATE)
                print("[LIVE DEMO] New inbound manifest recorded")
                return

            active = [
                shipment for shipment in STATE.get("shipments", {}).values()
                if shipment.get("status") in NEXT_DEMO_EVENT
            ]
            if not active:
                self._new_manifest()
                save_state(STATE)
                print("[LIVE DEMO] New inbound manifest recorded")
                return

            shipment = min(
                active,
                key=lambda item: float((item.get("history") or [{}])[-1].get("ts", 0)),
            )
            event, role = NEXT_DEMO_EVENT[shipment["status"]]
            process_event(STATE, LEDGER, {
                "container_id": shipment["container_id"],
                "event": event,
                "role": role,
                "note": f"Demo IoT feed: {event.lower().replace('_', ' ')} event recorded",
            })
            save_state(STATE)
            print(f"[LIVE DEMO] {shipment['container_id']} -> {event}")

    def _run(self):
        while not self._stop.wait(self.interval):
            try:
                self._advance_one()
            except Exception as error:
                print(f"[LIVE DEMO] Event skipped: {type(error).__name__}: {error}")

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
        parsed_url = urlsplit(self.path)
        clean_path = parsed_url.path

        if clean_path in ("/", "/index.html"):
            public_path = STATIC_DIR / "public.html"
            content = public_path.read_text(encoding="utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(content.encode("utf-8"))

        elif clean_path in ("/admin", "/dashboard"):
            dashboard_path = STATIC_DIR / "dashboard.html"
            content = dashboard_path.read_text(encoding="utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(content.encode("utf-8"))

        elif clean_path == "/api/report.pdf":
            try:
                query = parse_qs(parsed_url.query)
                start_date = date.fromisoformat(query.get("from", [""])[0])
                end_date = date.fromisoformat(query.get("to", [""])[0])
                if end_date < start_date:
                    raise ValueError("The end date must be on or after the start date.")
                if (end_date - start_date).days > 366:
                    raise ValueError("Report ranges cannot exceed 366 days.")
                pdf = _report_for_dates(start_date, end_date)
                self.send_response(200)
                self.send_header("Content-Type", "application/pdf")
                self.send_header(
                    "Content-Disposition",
                    f'attachment; filename="voc-container-report-{start_date.isoformat()}-to-{end_date.isoformat()}.pdf"',
                )
                self.send_header("Content-Length", str(len(pdf)))
                self.end_headers()
                self.wfile.write(pdf)
            except (ValueError, IndexError) as error:
                self._json({"error": str(error) or "Provide valid from and to dates (YYYY-MM-DD)."}, 400)

        elif clean_path == "/api/state":
            with LOCK:
                ok, bad = LEDGER.verify()
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
                "live_demo": LIVE_DEMO,
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
    import argparse

    parser = argparse.ArgumentParser(description="VOC Port container tracker server")
    parser.add_argument(
        "--no-live-demo",
        action="store_true",
        help="Disable the automatic persisted demo IoT event feed",
    )
    args = parser.parse_args()
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
    if not args.no_live_demo:
        LIVE_DEMO = True
        LiveDemoFeed().start()
        print("[LIVE DEMO] Persisted container events enabled (5-second interval)")
    else:
        print("[INFO] Automatic demo event feed disabled")
    ThreadingHTTPServer(("0.0.0.0", 5000), Handler).serve_forever()