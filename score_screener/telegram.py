from __future__ import annotations

import json
from urllib import error, request


TELEGRAM_MESSAGE_LIMIT = 4096


def send_telegram_message(token: str, chat_id: str, text: str, timeout: int = 15) -> None:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    for chunk in split_telegram_message(text):
        payload = {
            "chat_id": chat_id,
            "text": chunk,
            "disable_web_page_preview": True,
        }
        encoded = json.dumps(payload).encode("utf-8")
        req = request.Request(url, data=encoded, headers={"Content-Type": "application/json"})
        try:
            with request.urlopen(req, timeout=timeout) as response:
                if response.status >= 400:
                    raise RuntimeError(f"Telegram API returned HTTP {response.status}")
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Telegram API error {exc.code}: {detail}") from exc
        except error.URLError as exc:
            raise RuntimeError(f"Telegram network error: {exc.reason}") from exc


def split_telegram_message(text: str, limit: int = TELEGRAM_MESSAGE_LIMIT) -> list[str]:
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    current: list[str] = []
    current_size = 0
    for line in text.splitlines():
        next_size = len(line) + 1
        if current and current_size + next_size > limit:
            chunks.append("\n".join(current))
            current = []
            current_size = 0
        if next_size > limit:
            chunks.extend(line[index : index + limit] for index in range(0, len(line), limit))
            continue
        current.append(line)
        current_size += next_size

    if current:
        chunks.append("\n".join(current))
    return chunks
