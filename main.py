import os
import re
from typing import Dict, List, Tuple

import requests
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import Response
from twilio.request_validator import RequestValidator
from twilio.twiml.messaging_response import MessagingResponse

# -----------------------------
# Config (через Render env vars)
# -----------------------------
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.2").strip()

BUBASHVABE_SYSTEM = os.getenv(
    "BUBASHVABE_SYSTEM",
    "Ты — Бубашвабе: тёплый, спокойный, заботливый домовой-помощник. Пиши по-русски, коротко и по шагам."
).strip()

# Включить проверку подписи Twilio (рекомендую включать после того, как всё стабильно работает)
REQUIRE_TWILIO_SIGNATURE = os.getenv("REQUIRE_TWILIO_SIGNATURE", "false").lower() in ("1", "true", "yes")

TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "").strip()
_validator = RequestValidator(TWILIO_AUTH_TOKEN) if TWILIO_AUTH_TOKEN else None

# Лимиты
OPENAI_TIMEOUT_SEC = float(os.getenv("OPENAI_TIMEOUT_SEC", "12"))
MAX_OUTPUT_TOKENS = int(os.getenv("MAX_OUTPUT_TOKENS", "350"))
MAX_HISTORY = int(os.getenv("MAX_HISTORY", "10"))

# Простейшая "память" в RAM (сбросится при перезапуске Render)
_history: Dict[str, List[Tuple[str, str]]] = {}  # phone -> [(role, text), ...]


app = FastAPI()


# -----------------------------
# Helpers
# -----------------------------
def _public_url(request: Request) -> str:
    """
    Для подписи Twilio важен ТОЧНЫЙ URL.
    За прокси бывает, что request.url = http://..., а реально снаружи https://...
    Попробуем восстановить по X-Forwarded-*.
    """
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
    path = request.url.path
    query = request.url.query
    if query:
        return f"{proto}://{host}{path}?{query}"
    return f"{proto}://{host}{path}"


def _is_sensitive(text: str) -> bool:
    t = text.lower()
    patterns = [
        r"\bпарол", r"\bpassword\b",
        r"\bкод\b", r"\bsms\b", r"\bсмс\b",
        r"\bcvv\b", r"\bcvc\b", r"\bpin\b",
        r"\bкарта\b", r"\bномер карты\b", r"\bбанковск",
        r"\bодноразов", r"\b2fa\b", r"\botp\b",
    ]
    return any(re.search(p, t) for p in patterns)


def _safe_refusal() -> str:
    return (
        "🪲 Я не могу помогать с паролями/кодами из SMS и данными карт — это небезопасно.\n"
        "Если хочешь, опиши задачу без секретных данных, и я подскажу безопасный способ."
    )


def _add_history(phone: str, role: str, text: str) -> None:
    items = _history.setdefault(phone, [])
    items.append((role, text))
    # режем хвост
    if len(items) > MAX_HISTORY * 2:
        _history[phone] = items[-MAX_HISTORY * 2:]


def _build_openai_input(phone: str, user_text: str):
    """
    Собираем сообщения для OpenAI из системного промпта + краткой истории.
    """
    msgs = [{"role": "system", "content": BUBASHVABE_SYSTEM}]

    for role, txt in _history.get(phone, [])[-MAX_HISTORY * 2:]:
        # role у нас "user"/"assistant"
        msgs.append({"role": role, "content": txt})

    msgs.append({"role": "user", "content": user_text})
    return msgs


def ask_openai(phone: str, user_text: str) -> str:
    if not OPENAI_API_KEY:
        # если ключ не задан — работаем как "эхо", чтобы бот был живой
        return f"🪲 Бубашвабе получил: {user_text}"

    headers = {
        "Autho
