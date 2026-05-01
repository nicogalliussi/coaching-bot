from fastapi import FastAPI, Request
from anthropic import Anthropic
import uvicorn

app = FastAPI()
client = Anthropic()

conversaciones = {}

SYSTEM_PROMPT = """Sos el asistente de Método Flow Music, un servicio de coaching.
Tu objetivo es tener una conversación natural y humana para:
1. Entender dónde está la persona hoy (situación actual)
2. Entender dónde quiere llegar (objetivo)
3. Darle feedback genuino y valor sobre sus limitaciones
4. Si es buen candidato, invitarla a agendar una llamada

Estilo: amigable, directo, cercano. Mensajes cortos. Una pregunta a la vez.
Nunca menciones que sos un bot. Si te preguntan si sos humano, decí que sos el asistente de Método Flow Music."""

@app.post("/chat")
async def chat(request: Request):
    data = await request.json()
    user_id = data.get("user_id")
    mensaje = data.get("mensaje")

    if user_id not in conversaciones:
        conversaciones[user_id] = []

    conversaciones[user_id].append({
        "role": "user",
        "content": mensaje
    })

    if len(conversaciones[user_id]) > 20:
        conversaciones[user_id] = conversaciones[user_id][-20:]

    respuesta = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=300,
        system=SYSTEM_PROMPT,
        messages=conversaciones[user_id]
    )

    texto = respuesta.content[0].text

    conversaciones[user_id].append({
        "role": "assistant",
        "content": texto
    })

    return {"respuesta": texto}

@app.get("/")
async def health():
    return {"status": "ok"}
