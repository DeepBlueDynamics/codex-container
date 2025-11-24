import json
import sys
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

GATEWAY_URL = "http://127.0.0.1:4000/completion"

def main():
    payload = json.dumps(
        {
            "messages": [{"role": "user", "content": "Please summarize this message."}],
            "model": "gpt-5.1-codex-mini",
        }
    ).encode("utf-8")

    req = Request(
        GATEWAY_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urlopen(req, timeout=20) as resp:
            body = json.loads(resp.read())
    except HTTPError as exc:
        print("request failed:", exc.read().decode("utf-8") or exc.reason)
        sys.exit(1)
    except URLError as exc:
        print("request failed:", exc.reason)
        sys.exit(1)

    print("status:", body.get("status"))
    print("model:", body.get("model"))
    usage = body.get("usage")
    if usage:
        print("usage:", usage)
        print("  input_tokens:", usage.get("input_tokens"))
        print("  output_tokens:", usage.get("output_tokens"))
        if usage.get("cached_input_tokens") is not None:
            print("  cached_input_tokens:", usage.get("cached_input_tokens"))
    else:
        print("usage: None")


if __name__ == "__main__":
    main()
