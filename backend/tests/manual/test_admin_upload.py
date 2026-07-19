"""Admin batch upload integration test."""
import urllib.request, json, os, tempfile

# Create a temporary text file
tmp = tempfile.NamedTemporaryFile(suffix=".txt", delete=False, mode="w", encoding="utf-8")
tmp.write("这是一个测试题目的内容。已知三角形ABC中，角A=30度，边BC=5，求边AB的长度。")
tmp.close()

boundary = "----FormBoundary7MA4YWxkTrZu0gW"
body = b""
for name, value in [("subject", "数学"), ("grade", "高中"), ("category", "几何")]:
    body += f"--{boundary}\r\n".encode()
    body += f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode()
    body += f"{value}\r\n".encode()

with open(tmp.name, "rb") as f:
    file_content = f.read()
body += f"--{boundary}\r\n".encode()
body += f'Content-Disposition: form-data; name="files"; filename="test.txt"\r\n'.encode()
body += f"Content-Type: text/plain\r\n\r\n".encode()
body += file_content + b"\r\n"
body += f"--{boundary}--\r\n".encode()

req = urllib.request.Request(
    "http://localhost:8000/api/admin/documents/batch-upload",
    data=body,
    method="POST",
)
req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
req.add_header("X-Admin-Key", "test-key")

try:
    r = urllib.request.urlopen(req, timeout=15)
    resp = json.loads(r.read().decode())
    print("Batch upload status:", r.status)
    print("Response:", json.dumps(resp, ensure_ascii=False, indent=2)[:800])
except urllib.error.HTTPError as e:
    print("Error:", e.code, e.read().decode()[:500])

os.unlink(tmp.name)
