from fastapi import FastAPI, Request
from fastapi.responses import Response
from twilio.twiml.messaging_response import MessagingResponse

app = FastAPI()

@app.get("/health")
def health():
    return {"ok": True}

@app.post("/whatsapp")
async def whatsapp_webhook(request: Request):
    form = await request.form()
    text = (form.get("Body") or "").strip()

    resp = MessagingResponse()
    resp.message(f"🪲 Бубашвабе получил: {text}")

    # ВАЖНО: возвращаем XML (TwiML), а не JSON-строку
    return Response(content=str(resp), media_type="application/xml")
