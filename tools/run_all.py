"""Run every sample through the pipeline from a fresh demo state and print the decisions.

python tools/run_all.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

from app import config, store  # noqa: E402
from app.pipeline import execute, new_run  # noqa: E402

store.init(reset=True)
for p in sorted(config.SAMPLES.glob("*.pdf")):
    run = execute(new_run(p.name, p), lambda e: None)
    r = run.get("result") or {}
    print(f"{p.name[:46]:46s} {run['decision']:8s} {r.get('headline', '')}  [{r.get('owner', '')}] {run.get('error', '')}")
    for c in run.get("checks", []):
        if c["status"] in ("fail", "warn"):
            print(f"      - {c['severity']:6s} {c['id']:16s} {c['detail'][:170]}")
store.init(reset=True)
