# Dataset provenance & real-life references

The dataset `data/voc_port_dwell_dataset.csv` is **synthetic but calibrated** —
every parameter is anchored to a publicly documented fact about VOC Port /
Indian major ports. This must be stated honestly in the report.

| Parameter used | Real-life reference |
|---|---|
| ~82% terminal utilisation | VOC Port's two container terminals have ~1.02 M TEU combined capacity (PSA SICAL + DBGT / Tuticorin International Container Terminal) and the port handled ~0.87 M TEU in FY2025-26 — press and port reports consistently cite ~80% capacity utilisation. |
| NE monsoon penalty Oct–Dec | Thoothukudi lies on the Tamil Nadu coast in the north-east monsoon belt; monsoon swell and rain slow crane ops and occasionally close the port. |
| 18% customs exam rate, +~30 h | Risk-based customs examination at Indian ports typically covers 15-20% of containers and adds 1-3 days (terminal CFS exam logistics). |
| Reefer priority −14 h | Frozen seafood is Thoothukudi's signature export; reefer plugs and cold-chain protocol give reefer boxes clearance priority. |
| ~3% holiday rate | Major ports observe ~10-13 gazetted holidays per year. |
| Import base dwell > Export | Import containers at Indian ports typically dwell longer than exports (customs assessment, duty payment, CFS movement). |
| Congestion penalty above 80% | Queueing degrades sharply once utilisation crosses ~80% — standard port-operations knowledge. |

Target variable: `dwell_hours` — hours from berth arrival to gate-out (clearance).
