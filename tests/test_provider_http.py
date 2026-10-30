"""Exercise real HTTP request construction without provider credentials."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from modules.free_brain import _post_sync
from modules.provider_http import USER_AGENT
from tools import overlord_setup as setup


def test_setup_and_inference_identify_the_application():
    seen = []
    bodies = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def respond(self):
            length = int(self.headers.get("Content-Length", "0"))
            bodies.append(self.rfile.read(length) if length else b"")
            seen.append((self.command, self.headers.get('User-Agent'), self.headers.get('Authorization')))
            named = self.headers.get('User-Agent') == USER_AGENT
            self.send_response(200 if named else 403)
            self.end_headers()
            self.wfile.write(json.dumps({'data': []} if named else {'error_code': 1010}).encode())
        def do_GET(self): self.respond()
        def do_POST(self): self.respond()
    server = HTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f'http://127.0.0.1:{server.server_port}/api'
    try:
        assert setup._get(url, 'synthetic', 3)[0] == 200
        assert _post_sync(url, {'messages': []}, 'synthetic', 3)[0] == 200
        assert seen == [('GET', USER_AGENT, 'Bearer synthetic'), ('POST', USER_AGENT, 'Bearer synthetic')]
        assert bodies[0] == b'' and json.loads(bodies[1]) == {'messages': []}
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_security_filter_error_is_not_reported_as_an_invalid_key(monkeypatch):
    monkeypatch.setattr(setup, '_get', lambda *a: (403, json.dumps({
        'error_code': 1010, 'detail': 'private diagnostic never echoed'})))
    ok, message = setup.probe_key(setup.GROQ_MODELS_URL, 'synthetic', 'Groq')
    assert not ok and 'security filter' in message and 'key is invalid' in message
    assert 'copied completely' not in message and 'private diagnostic' not in message
