import os
import re
from typing import Dict, List

import requests
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse
from twilio.request_validator import RequestValidator
from twilio.twiml.messaging_response import MessagingResponse

app = FastAPI()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.2").strip() or "gpt-5.2"
BUBASHVABE_SYSTEM = os.getenv(
    "BUBASHVABE_SYSTEM", "Ты Бубашвабе — вежливый, полезный помощник."
).strip()
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "").strip()
REQUIRE_TWILIO_SIGNATURE = os.getenv("REQUIRE_TWILIO_SIGNATURE", "false").lower() in (
    "1",
    "true",
    "yes",
    "on",
)
OPENAI_TIMEOUT_SEC = int(os.getenv("OPENAI_TIMEOUT_SEC", "12"))
MAX_OUTPUT_TOKENS = int(os.getenv("MAX_OUTPUT_TOKENS", "350"))
MAX_HISTORY = int(os.getenv("MAX_HISTORY", "10"))

_memory: Dict[str, List[Dict[str, str]]] = {}

_SECRET_RE = re.compile(
    r"(пароль|код|sms|карта|cvv|otp|2fa|pin)", re.IGNORECASE
)


@app.get("/")
def root() -> JSONResponse:
    return JSONResponse({"ok": True})


@app.head("/")
def root_head() -> Response:
    return Response(status_code=200)


@app.get("/health")
def health() -> JSONResponse:
    return JSONResponse({"ok": True})


@app.get("/twiml")
def twiml_check() -> Response:
    resp = MessagingResponse()
    resp.message("test from Bubashvabe")
    return Response(content=str(resp), media_type="text/xml")


def _is_secret(text: str) -> bool:
    return bool(_SECRET_RE.search(text or ""))


def _build_full_url(request: Request) -> str:
    headers = request.headers
    proto = headers.get("x-forwarded-proto", request.url.scheme)
    host = headers.get("x-forwarded-host", headers.get("host"))
    path = request.url.path
    query = request.url.query
    if query:
        path = f"{path}?{query}"
    return f"{proto}://{host}{path}"


def _get_history(from_number: str) -> List[Dict[str, str]]:
    if not from_number:
        return []
    return _memory.get(from_number, []).copy()


def _append_history(from_number: str, role: str, content: str) -> None:
    if not from_number:
        return
    history = _memory.get(from_number, [])
    history.append({"role": role, "content": content})
    if len(history) > MAX_HISTORY:
        history = history[-MAX_HISTORY:]
    _memory[from_number] = history


def ask_openai(from_number: str, text: str) -> str:
    history = _get_history(from_number)
    payload = {
        "model": OPENAI_MODEL,
        "input": (
            [{"role": "system", "content": BUBASHVABE_SYSTEM}]
            + history
            + [{"role": "user", "content": text}]
        ),
        "max_output_tokens": MAX_OUTPUT_TOKENS,
    }
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }
    response = requests.post(
        "https://api.openai.com/v1/responses",
        json=payload,
        headers=headers,
        timeout=OPENAI_TIMEOUT_SEC,
    )
    response.raise_for_status()
    data = response.json()
    output_text = data.get("output_text")
    if output_text:
        return output_text
    for item in data.get("output", []) or []:
        for content in item.get("content", []) or []:
            text_value = content.get("text")
            if text_value:
                return text_value
    return "Сейчас не могу ответить, попробуйте позже."


@app.post("/whatsapp")
async def whatsapp_webhook(request: Request) -> Response:
    form = await request.form()
    from_number = form.get("From", "")
    text = form.get("Body", "")

    if REQUIRE_TWILIO_SIGNATURE:
        if not TWILIO_AUTH_TOKEN:
            return PlainTextResponse("Missing TWILIO_AUTH_TOKEN", status_code=500)
        signature = request.headers.get("X-Twilio-Signature", "")
        validator = RequestValidator(TWILIO_AUTH_TOKEN)
        url = _build_full_url(request)
        if not signature or not validator.validate(url, dict(form), signature):
            return PlainTextResponse("Invalid signature", status_code=403)

    if _is_secret(text):
        reply_text = "Похоже, это может содержать секреты. Я не могу это обрабатывать."
    else:
        if OPENAI_API_KEY:
            try:
                reply_text = ask_openai(from_number, text)
            except Exception as e:
                print("OPENAI ERROR", repr(e))
                reply_text = "Сервис временно недоступен. Попробуйте позже."
        else:
            reply_text = f"🪲 Бубашвабе получил: {text}"

    _append_history(from_number, "user", text)
    _append_history(from_number, "assistant", reply_text)

    resp = MessagingResponse()
    resp.message(reply_text)
    return Response(content=str(resp), media_type="text/xml")

from fastapi.responses import Response

@app.get("/", include_in_schema=False)
def root():
    return {"ok": True}

@app.head("/", include_in_schema=False)
def root_head():
    return Response(status_code=200)
