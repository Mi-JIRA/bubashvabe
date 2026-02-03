from fastapi import FastAPI, Request
from twilio.twiml.messaging_response import MessagingResponse

app = FastAPI()

@app.get("/health")
def health():
    return {"ok": True}

@app.post("/whatsapp")
async def whatsapp_webhook(request: Request):
    form = await request.form()
    text = form.get("Body", "")
    
    resp = MessagingResponse()
    resp.message(f"🪲 Бубашвабе получил: {text}")
    return str(resp)
