from fastapi import FastAPI, Request
from fastapi.responses import Response
from twilio.twiml.messaging_response import MessagingResponse

app = FastAPI()

@app.get("/health")
def health():
    return {"ok": True}

# тестовый endpoint — чтобы открыть в браузере и увидеть XML
@app.get("/twiml")
def twiml():
    r = MessagingResponse()
    r.message("test from Bubashvabe")
    return Response(content=str(r), media_type="text/xml")

@app.post("/whatsapp")
async def whatsapp_webhook(request: Request):
    form = await request.form()
    text = (form.get("Body") or "").strip()

    r = MessagingResponse()
    r.message(f"🪲 Бубашвабе получил: {text}")

    return Response(content=str(r), media_type="text/xml")
