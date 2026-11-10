"""Mechanical worker outcome accounting; model claims are never verification."""
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

TERMINAL = frozenset({'finished', 'incomplete', 'stalled', 'crashed', 'failed', 'interrupted', 'cancelled', 'rejected'})


def summarize(events, since=None):
    rows = {}
    for event in events:
        if event.get('brain') != 'free' or event.get('status') not in TERMINAL:
            continue
        at = event.get('finished_at') or event.get('timestamp') or event.get('recorded_at') or ''
        if since and at < since:
            continue
        identity = event.get('event_id')
        if not identity:
            raise ValueError('Terminal report lacks event_id; cannot deduplicate honestly')
        rows[identity] = event
    counts = Counter(e['status'] for e in rows.values())
    verified = [e for e in rows.values() if e['status'] == 'finished'
                and e.get('project_task_id') and (e.get('acceptance') or {}).get('passed') is True]
    finished = counts.get('finished', 0)
    durations = sum(float(e.get('duration_seconds') or 0) for e in rows.values())
    return {'since': since, 'terminal_runs': len(rows), 'status_counts': dict(sorted(counts.items())),
            'model_finished_runs': finished, 'verified_acceptance_runs': len(verified),
            'preflight_runs': sum(isinstance(e.get('acceptance_baseline'), dict) for e in rows.values()),
            'initially_failing_contracts': sum((e.get('acceptance_baseline') or {}).get('passed') is False for e in rows.values()),
            'unique_verified_tasks': sorted({e['project_task_id'] for e in verified}),
            'unverified_finished_runs': finished - len(verified),
            'verified_rate': round(len(verified) / len(rows), 4) if rows else None,
            'recorded_worker_seconds': round(durations, 3),
            'verified_reports': [{'event_id': e['event_id'], 'worker': e['name'], 'task_id': e['project_task_id']}
                                 for e in verified],
            'limitation': 'Acceptance verification is only as strong as the configured checks. Repeated task verification is not a new product deliverable; unique task IDs are counted separately.'}


def read_events(root):
    for name in ('events.1.jsonl', 'events.jsonl'):
        path = Path(root) / name
        if path.exists():
            for line in path.read_text(encoding='utf-8').splitlines():
                if line.strip():
                    yield json.loads(line)


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reports', type=Path, required=True)
    parser.add_argument('--since', help='Inclusive UTC ISO report timestamp')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = summarize(read_events(args.reports), args.since)
    result['generated_at'] = datetime.now(timezone.utc).isoformat()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
