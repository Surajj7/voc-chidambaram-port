"""Seed the VOC Port tracker with a realistic fleet across all 3 key categories:
  - YET TO ARRIVE (Inbound approaching vessels)
  - IN THE PORT (Active at berth, customs exam, cleared)
  - WHAT HAS LEFT (Dispatched out of gate onto NH-138)

Usage:
    python iot_simulator/seed_demo.py
"""
import json
import urllib.request

BASE = "http://localhost:5000"

def main():
    print("Calling VOC Port seed endpoint...")
    req = urllib.request.Request(
        BASE + "/api/seed", data=b"{}",
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            res = json.loads(r.read())
            print("[OK] Successfully seeded demo fleet:")
            print(f"  Total containers: {res.get('total_containers')}")
            print(f"  Blockchain ledger blocks: {res.get('blocks')}")
            print("  Open dashboard: http://localhost:5000")
    except Exception as e:
        print("! Error seeding fleet:", e)
        print("Make sure backend is running: python backend/app.py")

if __name__ == "__main__":
    main()
