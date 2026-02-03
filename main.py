import os, requests

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.2")
SYSTEM = os.getenv("BUBASHVABE_SYSTEM", "Ты — Бубашвабе.")

def ask_openai(user_text: str) -> str:
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": OPENAI_MODEL,
        "input": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": user_text},
        ],
    }
    r = requests.post("https://api.openai.com/v1/responses", headers=headers, json=payload, timeout=25)
    r.raise_for_status()
    data = r.json()

    # simplest: output_text часто есть
    text = (data.get("output_text") or "").strip()
    if text:
        return text

    # fallback: вытащим из output
    chunks = []
    for item in data.get("output", []):
        for c in item.get("content", []):
            if c.get("type") in ("output_text", "text") and c.get("text"):
                chunks.append(c["text"])
    return ("\n".join(chunks)).strip() or "🪲 Я задумался. Повтори, пожалуйста, ещё разок."
