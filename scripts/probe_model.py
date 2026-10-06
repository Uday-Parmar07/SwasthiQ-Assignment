#!/usr/bin/env python3
"""Small opt-in live smoke test of language routed to the model planner."""
import json
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from app.agent.orchestrator import run

payload = {
    'conversation_id': 'provider_smoke', 'today': '2026-10-01',
    'turns': ['Harpreet Singh, 9812200311. Dr. Rao Saturday morning appointment. Kindly pencil me in.'],
}
try:
    response = run(**payload)
    result = response.model_dump()
    success = response.terminal_state == 'booked' and response.patient_id == 'pt_0013' and response.metrics.tokens > 0
    report = {'payload': payload, 'passed': success, 'response': result}
except Exception as exc:
    cause = exc.__cause__ or exc
    report = {'payload': payload, 'passed': False, 'error_type': type(cause).__name__, 'status_code': getattr(cause, 'status_code', None)}
path = ROOT / 'evaluation/provider-smoke.json'
path.parent.mkdir(exist_ok=True)
path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n')
print(json.dumps({'passed': report['passed'], 'metrics': report.get('response', {}).get('metrics'), 'error_type': report.get('error_type'), 'status_code': report.get('status_code')}))
raise SystemExit(0 if report['passed'] else 1)
