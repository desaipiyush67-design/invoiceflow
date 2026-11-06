"""Run every sample through the AI pipeline from a fresh demo state and print the decisions.

python tools/run_all.py            all samples
python tools/run_all.py 04 05      only these
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

from app import config, store  # noqa: E402
from app.pipeline import execute, new_run  # noqa: E402

only = sys.argv[1:]
store.init(reset=True)
for p in sorted(config.SAMPLES.glob("*.pdf")):
    if only and p.name[:2] not in only:
        continue
    run = execute(new_run(p.name, p), lambda e: None)
    r = run.get("result") or {}
    print(f"{p.name[:46]:46s} {run['decision']:8s} {run['duration_ms'] / 1000:5.1f}s  {r.get('headline', '')}  [{r.get('owner', '')}] {run.get('error', '')}", flush=True)
    for c in run.get("checks", []):
        if c["severity"] != "none" or c["status"] in ("fail", "warn"):
            print(f"      - {c['severity']:6s} {c['id'][:22]:22s} {c['detail'][:160]}")
store.init(reset=True)
