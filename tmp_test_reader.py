import json, pathlib, time

path=pathlib.Path('tmpreq.jsonl')
if path.exists():
    path.unlink()
text='Hello, world!'
# append
path.parent.mkdir(parents=True, exist_ok=True)
with path.open('a', encoding='utf-8') as f:
    f.write(json.dumps({'at':time.time_ns(),'text':text}, ensure_ascii=False)+'\n')
print('size after append', path.stat().st_size)
# read

def read_requests(pth, offset=0):
    try:
        size=pth.stat().st_size
    except:
        return [], offset
    if size < offset:
        offset=0
    if size == offset:
        return [], offset
    with pth.open('r',encoding='utf-8',errors='replace') as stream:
        stream.seek(offset)
        content=stream.read()
    if not content.endswith('\n'):
        last_newline=content.rfind('\n')
        if last_newline==-1:
            return [], offset
        content=content[:last_newline+1]
    messages=[]
    for line in content.splitlines():
        line=line.strip()
        if not line:
            continue
        try:
            payload=json.loads(line)
        except:
            continue
        if isinstance(payload, dict) and isinstance(payload.get('text'), str):
            t=payload['text'].strip()
            if t:
                messages.append(t)
    return messages, offset+len(content.encode('utf-8'))

msgs, off=read_requests(path,0)
print('msgs1',msgs,'off1',off)
msgs2, off2=read_requests(path,off)
print('msgs2',msgs2,'off2',off2)
