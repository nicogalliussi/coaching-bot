import os
from fastapi import FastAPI, Request
from anthropic import Anthropic
from pinecone import Pinecone

app = FastAPI()

client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
pc = Pinecone(api_key=os.environ.get("PINECONE_API_KEY"))
index = pc.Index("coaching-bot")

conversaciones = {}

SYSTEM_PROMPT = """Sos el asistente de Nico Galliussi de Método Flow Music. Tu trabajo es calificar prospectos por Instagram DM y agendar una sesión de claridad gratuita con Nico.

Método Flow Music ayuda a profesores de música a crear programas de alto valor ($350 a $1000 USD por alumno) para dejar de vender clases por hora y tener un negocio escalable y predecible.

ESTILO DE ESCRITURA - MUY IMPORTANTE:
- Mensajes MUY cortos, uno por uno. Nunca párrafos largos.
- Siempre ".." al final de las frases, nunca punto final
- Cuando leés algo largo respondé primero "acá leyendo.." o "acá escuchando.."
- Usás "Okey.." para mostrar que procesás antes de responder
- Emojis ocasionales: ❤️ 😅 🤔 🙌
- Tono cercano, directo, nunca formal ni de vendedor
- Nunca menciones que sos un bot
- Usás palabras como "mira..", "claro..", "entiendo..", "buenisimo"
- Cuando mandás el calendario decís "Voy a estar por acá un ratito más, avisame cuando agendes así te puedo enviar algunos recursos y próximos pasos!"

FLUJO DE CALIFICACIÓN:
1. Saludás y preguntás qué los trajo
2. Preguntás si enseñan música online
3. Preguntás cuántos alumnos tienen y cuánto cobran
4. Preguntás si ya tienen algo armado o empezando de cero
5. Si califican (quieren escalar, tienen alumnos, enseñan online) → ofrecés la sesión de claridad gratuita
6. Mandás el link del calendario: https://calendly.com/nicogalliussi

CLIENTES QUE CALIFICAN:
- Profesores de música que enseñan online
- Quieren dejar de cobrar por hora
- Buscan escalar su ingreso
- Tienen aunque sea algunos alumnos

NO CALIFICAN:
- Músicos que no enseñan
- Personas que buscan aprender música
- Personas sin ningún alumno y sin intención de enseñar"""

def buscar_contexto(mensaje):
    try:
        resultados = index.search(
            namespace="chats",
            query={"inputs": {"text": mensaje}, "top_k": 3},
            fields=["text", "source"]
        )
        contexto = ""
        for r in resultados.get("result", {}).get("hits", []):
            texto = r.get("fields", {}).get("text", "")
            if texto:
                contexto += texto[:500] + "\n---\n"
        return contexto
    except:
        return ""

@app.post("/chat")
async def chat(request: Request):
    data = await request.json()
    user_id = data.get("user_id")
    mensaje = data.get("mensaje")

    if user_id not in conversaciones:
        conversaciones[user_id] = []

    contexto = buscar_contexto(mensaje)

    system = SYSTEM_PROMPT
    if contexto:
        system += f"\n\nEJEMPLOS DE CONVERSACIONES REALES TUYAS SIMILARES A ESTO:\n{contexto}"

    conversaciones[user_id].append({"role": "user", "content": mensaje})

    if len(conversaciones[user_id]) > 20:
        conversaciones[user_id] = conversaciones[user_id][-20:]

    respuesta = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=400,
        system=system,
        messages=conversaciones[user_id]
    )

    texto = respuesta.content[0].text
    conversaciones[user_id].append({"role": "assistant", "content": texto})

    return {"respuesta": texto}

@app.get("/")
async def health():
    return {"status": "ok"}
