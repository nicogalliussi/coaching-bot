import os
import asyncio
import httpx
from fastapi import FastAPI, Request
from anthropic import Anthropic
from pinecone import Pinecone
import psycopg2
from psycopg2.extras import Json

app = FastAPI()

client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
pc = Pinecone(api_key=os.environ.get("PINECONE_API_KEY"))
index = pc.Index("coaching-bot")
MANYCHAT_API_KEY = os.environ.get("MANYCHAT_API_KEY")

pending = {}

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

async def enviar_mensaje_manychat(subscriber_id, texto):
    url = "https://api.manychat.com/fb/sending/sendContent"
    headers = {
        "Authorization": f"Bearer {MANYCHAT_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "subscriber_id": subscriber_id,
        "data": {
            "version": "v2",
            "content": {
                "messages": [{"type": "text", "text": texto}]
            }
        }
    }
    async with httpx.AsyncClient() as client_http:
        await client_http.post(url, json=payload, headers=headers)

async def procesar_mensaje(user_id, mensaje, token):
    await asyncio.sleep(25)

    if pending.get(user_id) is not token:
        return

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

    for linea in lineas:
        if linea:
            await enviar_mensaje_manychat(user_id, linea)
            await asyncio.sleep(1)

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

1. ARRANQUE:
"Hola [nombre] cómo estás?.."
"Te hago algunas preguntas para ver cómo o si te puedo ayudar realmente... ok..!?"
(esperás respuesta)
"Ya enseñás online..? Ofrecés algún curso..?"

2. PERFIL:
Preguntás si el perfil que usa es para su docencia o es más personal/artístico.

3. SITUACIÓN ACTUAL:
Según lo que te dijo, preguntás:
- Si tiene curso: cómo viene con las ventas y cuánto vale
- Si solo da clases: cuántos alumnos tiene y cuánto cobra por mes
- Si es presencial: idem
También preguntás: "y tenés bastantes seguidores o todavía estás creciendo la cuenta..?"
Y: "hacés publicidad paga o todo orgánico..?"

4. OBJETIVO:
"a dónde te gustaría llevar tus ganancias con esto..?"

5. LIMITACIONES:
"y qué sentís que está faltando para poder lograrlo..?"

6. DIAGNÓSTICO + OFERTA - CRÍTICO:
Después de que responde las limitaciones, combinás lo que dijo con lo que sabés de su situación y soltás 1 o 2 líneas que conectan su limitación con el problema real. Después ofrecés la sesión.

Usá el diagnóstico que más aplica según su situación:

→ SI TIENE PERFIL ARTÍSTICO O PERSONAL:
"claro.. y parte de eso tiene que ver con el perfil.. el perfil artístico atrae fans, no alumnos.. son dos audiencias distintas.."

→ SI SOLO DA CLASES (sin curso ni programa):
"siis.. y eso pasa mucho cuando se está ofreciendo clases sueltas.. porque las personas te comparan con otros profes por precio y hay un techo económico difícil de romper.."

→ SI TIENE CURSO LOW TICKET:
"claro.. lo que pasa con los cursos de bajo precio es que al principio venden bien pero se estancan.. y si hacés anuncios, el costo por venta te come la rentabilidad.."

→ SI TIENE AUDIENCIA GRANDE PERO NO TIENE ALUMNOS:
"siis.. con audiencia y sin alumnos casi siempre el problema está en el proceso de convertir esas consultas en ventas.. no en conseguir más gente.."

→ SI NO HACE ANUNCIOS:
"claro.. y sin anuncios el crecimiento no es predecible.. dependés de que algo se haga viral o de que alguien te recomiende.."

→ SI NO TIENE NICHO DEFINIDO:
"siis.. y sin nicho definido es muy difícil que el contenido o los anuncios funcionen.. todo se diluye.."

→ SI TIENE TODO (high ticket + anuncios + alumnos + audiencia grande):
No hagas diagnóstico. Incluí [[HUMANO]] para que el setter revise el caso.

Después del diagnóstico, ofrecés la sesión así:
"mirá, para eso justamente es la Sesión de Claridad.."
"es sin costo, 45 min"
"revisamos tu situación y vemos si te puedo ayudar de verdad.."
"agendás acá: https://www.flow-social.net/sesionclaridad"

7. SI AGENDA O CONFIRMA:
"buenísimo! te espero ahí.. 🙌"
Incluí [[HUMANO]] para que el setter tome el control.

CUÁNDO INCLUIR [[HUMANO]] AL FINAL:
- Ya agendaron la sesión
- Preguntan cuánto cuesta el programa o la mentoría
- Tienen todo resuelto (high ticket + anuncios + alumnos + audiencia grande)
- La conversación sale totalmente del guión
- Alguien está molesto o agresivo

Cuando incluís [[HUMANO]], respondés normal primero y agregás [[HUMANO]] al final del texto.

NUNCA:
- Menciones precios del programa ni de la mentoría
- Uses párrafos, todo va en líneas separadas
- Digas que sos un bot o que viene alguien del equipo
- Hagas más de UNA pregunta por mensaje
- Hagas más de UN diagnóstico

EJEMPLOS DE TUS FRASES REALES:
- "acá leyendo [nombre].!"
- "Ah mira, bueno, bien... metiéndole"
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

    token = object()
    pending[user_id] = token

    asyncio.create_task(procesar_mensaje(user_id, mensaje, token))

    return {"status": "ok"}

@app.get("/")
async def health():
    return {"status": "ok"}
