"""Generate the deterministic golden-output JSON used to validate the JS port
of the SL2/SL4 attach engine. Output is byte-stable (generated_at nulled).
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from defender_acr_dashboard.service_attach.engine import build_model
from defender_acr_dashboard.service_attach.mapping import AttachConfig
from defender_acr_dashboard.service_attach.parser import parse_sl2_sl4
from defender_acr_dashboard.service_attach import export

FIXTURE = ROOT / "inputfolder" / "ACR Details SL2-SL4.xlsx"
OUT = ROOT / "web-app" / "tests" / "sl-golden.json"

parsed = parse_sl2_sl4(str(FIXTURE))
model = build_model(parsed, AttachConfig())
payload = export.build_json(model)
# Null the timestamp so the golden file is deterministic.
payload["meta"]["generated_at"] = None
OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"Wrote {OUT} ({OUT.stat().st_size} bytes)")
print("customers:", len(payload["customers"]))
print("book_attach_ratio:", payload["meta"]["book_attach_ratio"])
