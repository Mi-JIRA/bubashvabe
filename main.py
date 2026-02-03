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
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": OPENAI_MODEL,
        "input": _build_openai_input(phone, user_text),
        "max_output_tokens": MAX_OUTPUT_TOKENS,
    }

    r = requests.post(
        "https://api.openai.com/v1/responses",
        headers=headers,
        json=payload,
        timeout=OPENAI_TIMEOUT_SEC,
    )
    r.raise_for_status()
    data = r.json()

    # основной путь
    out = (data.get("output_text") or "").strip()
    if out:
        return out

    # fallback: вытащим из output массива
    chunks = []
    for item in data.get("output", []):
        for c in item.get("content", []):
            if c.get("type") in ("output_text", "text") and c.get("text"):
                chunks.append(c["text"])
    out = "\n".join(chunks).strip()
    return out or "🪲 Я задумался. Повтори, пожалуйста, ещё разок."


# -----------------------------
# Endpoints
# -----------------------------
@app.get("/health")
def health():
    return {"ok": True}


@app.get("/twiml")
def twiml_test():
    """
    Быстрая проверка, что Render отдаёт XML корректно.
    Открой в браузере: https://<service>.onrender.com/twiml
    """
    r = MessagingResponse()
    r.message("test from Bubashvabe")
    return Response(content=str(r), media_type="text/xml")


@app.post("/whatsapp")
async def whatsapp_webhook(request: Request):
    # Twilio присылает application/x-www-form-urlencoded
    form = await request.form()
    params = dict(form)

    user_text = (params.get("Body") or "").strip()
    from_number = (params.get("From") or "").strip()  # например "whatsapp:+123..."

    # 1) Опциональная проверка подписи Twilio
    if REQUIRE_TWILIO_SIGNATURE:
        if not _validator or not TWILIO_AUTH_TOKEN:
            raise HTTPException(status_code=500, detail="TWILIO_AUTH_TOKEN is not set")

        signature = request.headers.get("X-Twilio-Signature", "")
        url = _public_url(request)

        if not _validator.validate(url, params, signature):
            raise HTTPException(status_code=403, detail="Invalid Twilio signature")

    # 2) Базовая безопасность
    if _is_sensitive(user_text):
        answer = _safe_refusal()
    else:
        # 3) Память + OpenAI
        _add_history(from_number, "user", user_text)
        try:
            answer = ask_openai(from_number, user_text)
        except Exception:
            answer = "🪲 У меня сейчас лапки заняты. Попробуй ещё раз через минутку."

        _add_history(from_number, "assistant", answer)

    # 4) TwiML ответ
    tw = MessagingResponse()
    tw.message(answer)
    return Response(content=str(tw), media_type="text/xml")
