import json
from typing import Generator
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

import config

_http_session: requests.Session | None = None


def _get_session() -> requests.Session:
    global _http_session
    if _http_session is None:
        _http_session = requests.Session()
        retry = Retry(
            total=3,
            backoff_factor=0.3,
            status_forcelist=[502, 503, 504],
            allowed_methods=["POST"],
        )
        adapter = HTTPAdapter(max_retries=retry)
        _http_session.mount("http://", adapter)
        _http_session.mount("https://", adapter)
    return _http_session


def stream_response(
    user_text: str,
    history: list[dict] | None = None,
) -> Generator[str, None, None]:
    """Send user_text to OpenClaw /v1/responses with streaming.

    Yields text deltas as they arrive via SSE.
    When *history* is provided, the full conversation context is sent as an
    array of ``{"role": ..., "content": ...}`` items.
    """
    url = f"{config.OPENCLAW_BASE_URL}/v1/responses"
    headers = {
        "Authorization": f"Bearer {config.OPENCLAW_TOKEN}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }

    if history:
        input_val: str | list[dict] = [
            {"type": "message", "role": m["role"], "content": m["content"]}
            for m in history
        ]
        input_val.append({"type": "message", "role": "user", "content": user_text})
    else:
        input_val = user_text

    body = {
        "model": "openclaw",
        "stream": True,
        "input": input_val,
    }

    print(f"[openclaw] POST {url} (stream=true)")

    try:
        resp = _get_session().post(url, json=body, headers=headers, stream=True, timeout=(30, 120))
    except (requests.ConnectionError, requests.Timeout) as e:
        raise RuntimeError(f"Cannot reach OpenClaw at {config.OPENCLAW_BASE_URL}: {e}") from e

    if resp.status_code != 200:
        raise RuntimeError(
            f"OpenClaw request failed ({resp.status_code}): {resp.text[:300]}"
        )

    # Process stream in small chunks so we yield tokens as soon as a full SSE line
    # arrives (lower latency than iter_lines() with default buffering).
    event_type = None
    buf = ""
    for chunk in resp.iter_content(chunk_size=512, decode_unicode=True):
        if chunk is None:
            continue
        buf += chunk
        while "\n" in buf or "\r" in buf:
            line, _, buf = buf.partition("\n")
            line = line.strip().rstrip("\r")
            if not line:
                event_type = None
                continue
            if line.startswith("event:"):
                event_type = line[len("event:"):].strip()
                continue
            if line.startswith("data:"):
                data_str = line[len("data:"):].strip()
                if not data_str or data_str == "[DONE]":
                    continue
                try:
                    data = json.loads(data_str)
                except json.JSONDecodeError:
                    continue
                msg_type = data.get("type", "")
                if msg_type == "response.output_text.delta":
                    delta = data.get("delta", "")
                    if delta:
                        yield delta
                elif msg_type == "response.content_part.added":
                    part = data.get("part", {})
                    text = part.get("text", "")
                    if text:
                        yield text
                elif msg_type == "response.completed":
                    return
                elif msg_type == "error":
                    err_msg = data.get("error", {}).get("message", str(data))
                    raise RuntimeError(f"OpenClaw stream error: {err_msg}")
