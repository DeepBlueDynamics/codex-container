import json
import time
import requests

GATEWAY = "http://localhost:4000/completion"

payload = {
    "messages": [
        {
            "role": "user",
            "content": "Run a shell command to print SESSION_ID, CODEx envs, and ANTHROPIC_API_KEY length. Use: env | sort. Return as plain text."  # noqa: E501
        }
    ],
    "env": {
        "SESSION_ID_ECHO": "1"
    },
    "timeout_ms": 60000,
    "persistent": False
}

res = requests.post(GATEWAY, json=payload, timeout=120)
print(res.status_code)
try:
    print(json.dumps(res.json(), indent=2))
except Exception:
    print(res.text)
