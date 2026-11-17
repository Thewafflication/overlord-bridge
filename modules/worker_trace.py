"""Two bounded, redacted provider exchanges per worker/project for diagnosis.

These are transport observations, never completion or acceptance evidence.
Headers, credentials and provider URLs are not part of the capture contract.
"""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import uuid

from modules.command_activity import redact_text

MAX_REQUEST_BYTES = 192_000
MAX_RESPONSE_BYTES = 48_000
MAX_FILE_BYTES = 256_000


def _encoded(value):
    return json.dumps(value, ensure_ascii=False).encode('utf-8')


def _redacted(value):
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, list):
        return [_redacted(item) for item in value]
    if isinstance(value, dict):
        return {key: _redacted(item) for key, item in value.items()}
    return value


def _bounded(value, limit):
    value = _redacted(value)
    raw = _encoded(value)
    if len(raw) <= limit:
        return value
    return {'omitted': True, 'reason': 'capture_byte_limit',
            'redacted_bytes': len(raw), 'redacted_sha256': hashlib.sha256(raw).hexdigest()}


class WorkerRequestTrace:
    def __init__(self, reports, folder, name):
        identity = [os.path.normcase(str(Path(folder).resolve())), name]
        scope = hashlib.sha256(_encoded(identity)).hexdigest()
        self.directory = Path(reports).absolute() / 'requests'
        self.paths = [self.directory / f'{scope}-{slot}.json' for slot in range(2)]

    def _check(self):
        for path in [self.directory, *self.directory.parents, *self.paths]:
            if path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction()):
                raise ValueError('Linked worker request storage is not allowed')
        self.directory.mkdir(parents=True, exist_ok=True)

    def _write(self, path, record):
        raw = _encoded(record)
        if len(raw) > MAX_FILE_BYTES:
            raise ValueError('Worker request capture exceeds file bound')
        temporary = self.directory / (uuid.uuid4().hex + '.tmp')
        try:
            with temporary.open('xb') as stream:
                stream.write(raw)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)

    def begin(self, *, model, payload, run, step):
        self._check()
        path = min(self.paths, key=lambda p: p.stat().st_mtime_ns if p.exists() else -1)
        capture_id = uuid.uuid4().hex
        # Explicit allowlist prevents future callers from persisting HTTP auth,
        # endpoints or headers alongside the model input.
        request = {key: payload[key] for key in
                   ('model', 'messages', 'tools', 'tool_choice', 'temperature', 'max_tokens',
                    'reasoning_effort', 'provider') if key in payload}
        self._write(path, {'capture_id': capture_id, 'run': run, 'step': step,
                          'model': model, 'started_at': datetime.now(timezone.utc).isoformat(),
                          'state': 'pending', 'redacted': True,
                          'request': _bounded(request, MAX_REQUEST_BYTES),
                          'limitation': 'Provider payload after fitting, with redaction. Pending is not a crash. '
                                        'Only the last two attempts are retained; not acceptance evidence.'})
        return capture_id

    def finish(self, capture_id, *, status=None, body=None, error=None):
        self._check()
        for path in self.paths:
            if not path.exists() or path.stat().st_size > MAX_FILE_BYTES:
                continue
            record = json.loads(path.read_text(encoding='utf-8'))
            if record.get('capture_id') != capture_id:
                continue
            record.update(state='returned' if error is None else 'transport_error',
                          finished_at=datetime.now(timezone.utc).isoformat(), http_status=status)
            # Do not save provider errors, URLs, headers or exception messages.
            # The assistant message and finish reason suffice to inspect the
            # next decision. Tool arguments remain unexecuted observations.
            choices = body.get('choices') if isinstance(body, dict) else None
            choice = choices[0] if isinstance(choices, list) and choices else None
            if isinstance(choice, dict):
                record['response'] = _bounded({key: choice[key] for key in
                                              ('message', 'finish_reason') if key in choice}, MAX_RESPONSE_BYTES)
            if error is not None:
                record['error_type'] = error
            self._write(path, record)
            return
