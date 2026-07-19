import urllib.request
import urllib.parse
import json
import sys
sys.stdout.reconfigure(encoding='utf-8')

# Step 1: Ask
data = urllib.parse.urlencode({'question_text': '3+5='}).encode()
req = urllib.request.Request(
    'http://localhost:8000/api/student/ask',
    data=data,
    headers={'Content-Type': 'application/x-www-form-urlencoded'}
)
r = urllib.request.urlopen(req, timeout=120)
sq_id = None; sid = None
for _ in range(30):
    line = r.readline().decode('utf-8')
    if line.startswith('data:'):
        d = json.loads(line[5:].strip())
        if 'student_question_id' in d: sq_id = d['student_question_id']
        if 'session_id' in d: sid = d['session_id']
        if d.get('phase') == 'hint':
            print('HINT:', d.get('thinking_hint', '')[:200])

print('\n--- SOLUTION ---')

# Step 2: Choose explain
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
            print('ANSWER:', sol.get('answer', ''))
            for s in sol.get('steps', []):
                desc = str(s.get('description', ''))[:200]
                step_num = s.get('step', '?')
                print(f'  Step {step_num}: {desc}')
            print('SUMMARY:', str(sol.get('summary', ''))[:200])

print('DONE')
