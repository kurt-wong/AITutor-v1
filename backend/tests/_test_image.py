import urllib.request
import json
import sys
import struct
import zlib
sys.stdout.reconfigure(encoding='utf-8')

def create_png():
    def chunk(chunk_type, data):
        c = chunk_type + data
        crc = struct.pack('>I', zlib.crc32(c) & 0xffffffff)
        return struct.pack('>I', len(data)) + c + crc
    ihdr = struct.pack('>IIBBBBB', 1, 1, 8, 2, 0, 0, 0)
    raw = b'\x00\xff\x00\x00'
    idat = zlib.compress(raw)
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', ihdr) + chunk(b'IDAT', idat) + chunk(b'IEND', b'')

png_bytes = create_png()
boundary = b'----TestBoundary123'

body = b''
body += b'--' + boundary + b'\r\n'
body += b'Content-Disposition: form-data; name="question_text"\r\n\r\n'
body += b'\r\n'
body += b'--' + boundary + b'\r\n'
body += b'Content-Disposition: form-data; name="image"; filename="test.png"\r\n'
body += b'Content-Type: image/png\r\n\r\n'
body += png_bytes + b'\r\n'
body += b'--' + boundary + b'--\r\n'

req = urllib.request.Request(
    'http://localhost:8000/api/student/ask',
    data=body,
    headers={'Content-Type': 'multipart/form-data; boundary=' + boundary.decode()}
)
r = urllib.request.urlopen(req, timeout=60)
print('Status:', r.status)
sq_id = None; sid = None; q_text = None
for _ in range(30):
    line = r.readline().decode('utf-8')
    if line.startswith('data:'):
        d = json.loads(line[5:].strip())
        if d.get('phase') == 'processing_done':
            if d.get('question_text'):
                q_text = d['question_text']
                print('QUESTION_TEXT from vision:', q_text[:100])
        elif d.get('phase') == 'hint':
            sq_id = d.get('student_question_id')
            sid = d.get('session_id')
            print('HINT:', d.get('thinking_hint','')[:150])
        elif d.get('phase') == 'done':
            break
print(f'sq_id={sq_id} sid={sid}')

if sq_id and sid:
    import urllib.parse
    data2 = urllib.parse.urlencode({
        'student_question_id': str(sq_id),
        'choice': 'explain',
        'session_id': str(sid)
    }).encode()
    req2 = urllib.request.Request(
        'http://localhost:8000/api/student/choose',
        data=data2,
        headers={'Content-Type': 'application/x-www-form-urlencoded'}
    )
    r2 = urllib.request.urlopen(req2, timeout=120)
    for _ in range(60):
        line = r2.readline().decode('utf-8')
        if line.startswith('data:'):
            d = json.loads(line[5:].strip())
            if d.get('phase') == 'solution':
                sol = d['solution']
                print('SOL STEPS:', len(sol.get('steps',[])))
                for s in sol.get('steps',[])[:5]:
                    print(' -', s.get('step'), ':', str(s.get('description',''))[:120])
print('DONE')
