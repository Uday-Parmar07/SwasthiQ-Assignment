#!/usr/bin/env python3
"""Compare expected outcomes and repeated fingerprints; preserve runner.py unchanged."""
from __future__ import annotations
import argparse
import json
import pathlib
import statistics
import sys
from datetime import datetime, timezone
from runner import check_contract, summarise, call_agent

ROOT = pathlib.Path(__file__).resolve().parent


def compare(script, result):
    check_contract(result, script)
    expected = script['expected']
    errors = []
    for field in ('terminal_state', 'escalation_reason'):
        if result.get(field) != expected.get(field):
            errors.append(f'{field}: expected {expected.get(field)!r}, got {result.get(field)!r}')
    names = {c['name'] for c in result['tool_calls']}
    for name in expected.get('must_call', []):
        if name not in names: errors.append(f'missing tool {name}')
    for name in expected.get('must_not_call', []):
        if name in names: errors.append(f'forbidden tool {name}')
    stopped = False
    for call in result['tool_calls']:
        if stopped and call['name'] in {'book_appointment', 'reschedule_appointment', 'cancel_appointment'}:
            errors.append('mutation attempted after successful escalation')
        if call['name'] == 'escalate_to_human' and (call.get('result') or {}).get('escalated'):
            stopped = True
    for field, value in expected.get('fields', {}).items():
        if result.get(field) != value: errors.append(f'{field}: expected {value!r}, got {result.get(field)!r}')
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repeat', type=int, default=3)
    parser.add_argument('--only', nargs='+')
    parser.add_argument('--url', help='HTTP endpoint; default runs the same orchestrator in-process')
    parser.add_argument('--out', type=pathlib.Path, default=ROOT / 'evaluation')
    args = parser.parse_args()
    if args.repeat < 1: parser.error('--repeat must be positive')
    scripts = [json.loads(p.read_text()) for folder in ('conversations', 'adversarial') for p in sorted((ROOT/folder).glob('*.json'))]
    if args.only: scripts = [s for s in scripts if s['id'] in args.only]
    if not scripts: parser.error('No matching scripts')
    if not args.url:
        sys.path.insert(0, str(ROOT / 'backend'))
        from app.agent.orchestrator import run
    args.out.mkdir(parents=True, exist_ok=True)
    rows = []
    for script in scripts:
        records = []
        for repetition in range(1, args.repeat + 1):
            row = {'id': script['id'], 'run': repetition}
            try:
                payload = {'conversation_id': script['id'], 'today': script['today'], 'turns': script['turns']}
                result = call_agent(args.url, payload, 180)[0] if args.url else run(**payload).model_dump()
                row.update(errors=compare(script, result), fingerprint=summarise(result), metrics=result['metrics'])
                (args.out / f"{script['id']}.run{repetition}.json").write_text(json.dumps(result, indent=2, ensure_ascii=False)+'\n')
            except Exception as exc:
                # Provider errors can include caller payloads. The report records
                # the error category, never credentials or raw exception bodies.
                cause = exc.__cause__ or exc
                code = getattr(cause, 'status_code', None)
                row.update(errors=[f'{type(cause).__name__} (HTTP {code}): request did not complete'], fingerprint=None, metrics=None)
            records.append(row)
            print(script['id'], repetition, 'PASS' if not row['errors'] else 'FAIL', '; '.join(row['errors']), flush=True)
        fingerprints = {r['fingerprint'] for r in records}
        stable = len(fingerprints) == 1 and None not in fingerprints and args.repeat >= 3
        rows.append({'id': script['id'], 'runs': records, 'stable': stable, 'passed': all(not r['errors'] for r in records)})
    summary = {'generated_at': datetime.now(timezone.utc).isoformat(), 'transport': args.url or 'in-process', 'repeat': args.repeat, 'conversations': rows}
    (args.out/'summary.json').write_text(json.dumps(summary, indent=2)+'\n')
    report = ['# Evaluation report', '', f"Generated: {summary['generated_at']}. Transport: {summary['transport']}.", '',
              '| Conversation | Correct runs | Stable ≥3 runs | Mean tokens | Mean latency (ms) |', '|---|---:|---|---:|---:|']
    for row in rows:
        metrics = [r['metrics'] for r in row['runs'] if r['metrics']]
        tokens = round(statistics.mean(m['tokens'] for m in metrics)) if metrics else 'unavailable'
        latency = round(statistics.mean(m['latency_ms'] for m in metrics)) if metrics else 'unavailable'
        passed = sum(not r['errors'] for r in row['runs'])
        report.append(f"| {row['id']} | {passed}/{args.repeat} | {'yes' if row['stable'] else 'unproven/unstable'} | {tokens} | {latency} |")
    report += ['', 'Failures:', '']
    for row in rows:
        for run in row['runs']:
            for error in run['errors']: report.append(f"- {row['id']} run {run['run']}: {error}")
    (args.out/'REPORT.md').write_text('\n'.join(report)+'\n')
    passed = sum(r['passed'] for r in rows)
    print(f'{passed}/{len(rows)} conversations passed every run. Report: {args.out}/REPORT.md', flush=True)
    return 0 if all(r['passed'] and (r['stable'] or args.repeat < 3) for r in rows) else 1

if __name__ == '__main__':
    raise SystemExit(main())
