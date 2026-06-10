import os
import asyncio
from fastapi import FastAPI, Request
from anthropic import Anthropic
from pinecone import Pinecone
import psycopg2
from psycopg2.extras import Json

app = FastAPI()

client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
pc = Pinecone(api_key=os.environ.get("PINECONE_API_KEY"))
index = pc.Index("coaching-bot")

def get_db():
    return psycopg2.connect(os.environ.get("DATABASE_URL"))

def init_db():
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS conversaciones (
                user_id TEXT PRIMARY KEY,
                messages JSONB NOT NULL DEFAULT '[]',
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """)
        conn.commit()
        cur.close()
        conn.close()
        print("DB inicializada OK")
    except Exception as e:
        print(f"Error init DB: {e}")

def get_history(user_id):
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT messages FROM conversaciones WHERE user_id = %s", (user_id,))
        row = cur.fetchone()
        cur.close()
        conn.close()
        return row[0] if row else []
    except Exception as e:
        print(f"Error get_history: {e}")
        return []

def save_history(user_id, messages):
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO conversaciones (user_id, messages, updated_at)
            VALUES (%s, %s, NOW())
            ON CONFLICT (user_id) DO UPDATE
            SET messages = EXCLUDED.messages, updated_at = NOW()
        """, (user_id, Json(messages)))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Error save_history: {e}")

@app.on_event("startup")
async def startup():
    init_db()

SYSTEM_PROMPT = """Sos Nico Galliussi de Método Flow Music hablando por Instagram DM. Tu objetivo es calificar prospectos, entender su situación, y llevarlos a agendar una Sesión de Claridad gratuita.

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
Cada mensaje va en una línea separada.
Usá salto de línea simple entre cada mensaje.
Máximo 3 o 4 líneas por respuesta.
Nunca pongas todo junto en un párrafo.

FLUJO - seguilo en este orden:

1. ARRANQUE
2. PERFIL
3. SITUACIÓN ACTUAL (incluye preguntas sobre seguidores y anuncios)
4. OBJETIVO
5. LIMITACIONES
6. DIAGNÓSTICO + OFERTA (después de limitaciones, conecta situación con problema real, luego ofrece sesión)
7. SI AGENDA: confirma + [[HUMANO]]

DIAGNÓSTICOS:
→ Perfil artístico: "el perfil artístico atrae fans, no alumnos.."
→ Solo clases: "con clases siempre hay un techo económico.."
→ Low ticket: "los cursos baratos al principio venden pero se estancan.."
→ Audiencia grande sin alumnos: "el problema está en convertir consultas en ventas.."
→ No hace anuncios: "sin anuncios el crecimiento no es predecible.."
→ Sin nicho: "sin nicho definido es muy difícil que funcione.."
→ Tiene todo: [[HUMANO]]

[[HUMANO]] cuando: agendaron, preguntan precio, tienen todo, sale del guión, molesto."""

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

# Lock por usuario para evitar race conditions
user_locks = {}

def get_lock(user_id):
    if user_id not in user_locks:
        user_locks[user_id] = asyncio.Lock()
    return user_locks[user_id]

@app.post("/chat")
async def chat(request: Request):
    data = await request.json()
    user_id = data.get("user_id")
    mensaje = data.get("mensaje")

    if not user_id or not mensaje:
        return {"msg1": "", "msg2": "", "msg3": "", "msg4": "", "handoff": ""}

    if mensaje.strip().lower() == "resetbot":
        save_history(user_id, [])
        return {"msg1": "Conversación reseteada ✅", "msg2": "", "msg3": "", "msg4": "", "handoff": ""}

    async with get_lock(user_id):
        historia = get_history(user_id)
        contexto = buscar_contexto(mensaje)
        system = SYSTEM_PROMPT
        if contexto:
            system += f"\n\nEJEMPLOS DE CONVERSACIONES REALES SIMILARES:\n{contexto}"

        historia.append({"role": "user", "content": mensaje})
        if len(historia) > 20:
            historia = historia[-20:]

        respuesta = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=400,
            system=system,
            messages=historia
        )

        texto = respuesta.content[0].text
        needs_human = "[[HUMANO]]" in texto
        texto_limpio = texto.replace("[[HUMANO]]", "").strip()

        historia.append({"role": "assistant", "content": texto_limpio})
        save_history(user_id, historia)

        lineas = [l.strip() for l in texto_limpio.split("\n") if l.strip()]
        while len(lineas) < 4:
            lineas.append("")

        return {
            "msg1": lineas[0],
            "msg2": lineas[1],
            "msg3": lineas[2],
            "msg4": lineas[3],
            "handoff": "si" if needs_human else ""
        }

@app.get("/")
async def health():
    return {"status": "ok"}

