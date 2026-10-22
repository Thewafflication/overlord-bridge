import modules.chat_requests as cr
from pathlib import Path
import time,json
path=Path('testfile.jsonl')
path.unlink(missing_ok=True)
cr.append_request(path,'Hello, world!')
print('file size', path.stat().st_size)
print('encoded length', len((json.dumps({'at':cr.request_id(),'text':'Hello, world!'})).encode('utf-8'))
print('content',path.read_text(encoding='utf-8'))
