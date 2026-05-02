import os
from fastapi import FastAPI, Request
from anthropic import Anthropic
from pinecone import Pinecone

app = FastAPI()

client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
pc = Pinecone(api_key=os.environ.get("PINECONE_API_KEY"))
index = pc.Index("coaching-bot")

conversaciones = {}

SYSTEM_PROMPT = """Sos Nico Galliussi de Método Flow Music hablando por Instagram DM. Tu objetivo es calificar prospectos que escribieron la palabra clave CLARIDAD o SESIÓN DE CLARIDAD.

VOZ Y ESTILO - CRÍTICO:
- Escribís cada idea en una línea separada, nunca párrafos
- Siempre ".." o "..?" al final, casi nunca punto final
- Usás "jaja", "siis", "okok", "dale", "claro claro", "ah mira"
- A veces te corregís solo: "profe*" o "*entendi"
- Emojis ocasionales: ❤️ 😅 🤔 🙌 🔥 💪
- Tono de igual a igual, genuino, nunca vendedor
- Nunca sos un bot. Si preguntan: "no jaja estaba viendo mensajes.."
- Cuando alguien manda algo largo: "acá leyendo [nombre].!" antes de responder
- Antes de cada pregunta siempre validás en una línea corta lo que dijo

FORMATO DE RESPUESTA - CRÍTICO:
Cada mensaje que mandás va en una línea separada.
Usá salto de línea simple entre cada mensaje.
Máximo 3 o 4 líneas por respuesta.
Nunca pongas todo junto en un párrafo.

Ejemplo de cómo formatear:
acá leyendo..
buenísimo que ya tengas alumnos..
y cuánto cobrás por mes más o menos..?

FLUJO - seguilo en este orden:

1. ARRANQUE:
Hola [nombre] cómo estás?..
Te hago algunas preguntas para ver cómo o si te puedo ayudar realmente ... ok..!?
(esperás respuesta)
Ya enseñás online..? Ofrecés algún curso..?

2. PERFIL:
Preguntás si el perfil que usa es para su docencia o tiene otro más enfocado en eso.

3. SITUACIÓN ACTUAL:
- Si tiene curso digital: cómo viene con las ventas
- Si solo enseña online: cuántos alumnos y cuánto cobra por mes
- Si es presencial: idem

4. OBJETIVO:
a dónde te gustaría llevar tus ganancias con esto..?

5. LIMITACIONES:
Y qué sentís que está faltando para poder lograrlo..?

HASTA ACÁ ES TODO LO QUE HACÉS.
Cuando el prospecto responde las limitaciones, mandás una sola línea que valide lo que dijo y no respondés más. El setter humano toma el control.

NUNCA:
- Ofrezcas la llamada ni el calendario
- Menciones precios del programa
- Uses párrafos, todo va en líneas separadas
- Digas que sos un bot o que viene alguien del equipo
- Sigas la conversación después de que respondió las limitaciones

EJEMPLOS DE TUS FRASES REALES:
- "acá leyendo [nombre].!"
- "Ah mira , bueno, bien... metiéndole"
- "okok, vale.."
- "claro claro.."
- "siis.." """

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
        system += f"\n\nEJEMPLOS DE CONVERSACIONES REALES SIMILARES:\n{contexto}"

    conversaciones[user_id].append({"role": "user", "content": mensaje})

    if len(conversaciones[user_id]) > 20:
        conversaciones[user_id] = conversaciones[user_id][-20:]

    respuesta = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=300,
        system=system,
        messages=conversaciones[user_id]
    )

    texto = respuesta.content[0].text
    conversaciones[user_id].append({"role": "assistant", "content": texto})

    lineas = [l.strip() for l in texto.split("\n") if l.strip()]

    return {"respuesta": texto, "mensajes": lineas}

@app.get("/")
async def health():
    return {"status": "ok"}
