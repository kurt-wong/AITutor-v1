"""Quick test: MIMO-v2.5 multimodal (vision) API call."""
import httpx
import base64

API_KEY = "sk-cb5mm9uzaif0nbq29c637ojjhm1xj0ou8a4ri1vk9hgvv2wb"
BASE_URL = "https://api.xiaomimimo.com/v1"

# Minimal 1x1 transparent PNG (67 bytes, always valid)
MINI_PNG_B64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPj/HwADBwIAMCbHYQAAAABJRU5ErkJggg=="

print("=== Test 1: image_url format (mimo-v2.5) ===")
payload = {
    "model": "mimo-v2.5",
    "messages": [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "describe this image"},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{MINI_PNG_B64}"},
                },
            ],
        }
    ],
    "max_tokens": 100,
    "thinking": {"type": "disabled"},
}
r = httpx.post(
    f"{BASE_URL}/chat/completions",
    headers={
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    },
    json=payload,
    timeout=60,
)
print(f"Status: {r.status_code}")
if r.status_code == 200:
    data = r.json()
    print(f"Response: {data['choices'][0]['message']['content']}")
    print(f"Usage: {data.get('usage', {})}")
else:
    print(f"Error: {r.text[:500]}")

print("\n=== Test 2: text-only (mimo-v2.5 - verify) ===")
payload2 = {
    "model": "mimo-v2.5",
    "messages": [{"role": "user", "content": "reply with just the word: hello"}],
    "max_tokens": 20,
    "thinking": {"type": "disabled"},
}
r2 = httpx.post(
    f"{BASE_URL}/chat/completions",
    headers={
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    },
    json=payload2,
    timeout=60,
)
print(f"Status: {r2.status_code}")
if r2.status_code == 200:
    data2 = r2.json()
    content = data2['choices'][0]['message']['content']
    print(f"Response: '{content}'")
    print(f"Finish reason: {data2['choices'][0].get('finish_reason', 'N/A')}")
    # Also show thinking field if present
    if 'thinking' in data2['choices'][0]['message']:
        print(f"Thinking: {data2['choices'][0]['message']['thinking']}")
else:
    print(f"Error: {r2.text[:500]}")
