"""
FastAPI Backend - Chat com OpenAI + Fotos de Pratos via System Prompt
"""
import pathlib
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from openai import OpenAI
import json
import os
from dotenv import load_dotenv
import db  # módulo de acesso ao PostgreSQL (DigitalOcean)

# --- Caminho base (pasta onde está o main.py) ---
BASE_DIR = pathlib.Path(__file__).parent

# Inicializa o banco de dados (lê DATABASE_URL do .secret-env)
db.init_db(str(BASE_DIR))

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


load_dotenv(BASE_DIR / ".secret-env")
api_key = os.getenv("key")

if not api_key:
    raise ValueError("API key not found. Make sure 'key' is set in your .secret-env file.")


# --- Configuração ---
MODEL = "gpt-5-mini"
SYSTEM_PROMPT_FILE = BASE_DIR / "prompt_1.txt"

client = OpenAI(api_key=api_key)


def load_system_prompt():
    """Carrega o system prompt do arquivo usando caminho absoluto."""
    try:
        with open(SYSTEM_PROMPT_FILE, "r", encoding="utf-8") as f:
            conteudo = f.read().strip()
            print(f"✅ System prompt carregado: {SYSTEM_PROMPT_FILE} ({len(conteudo)} chars)")
            return conteudo
    except FileNotFoundError:
        print(f"⚠️ Arquivo não encontrado: {SYSTEM_PROMPT_FILE}")
        return "Você é um assistente útil e responde em português."
    except Exception as e:
        print(f"⚠️ Erro ao ler prompt: {e}")
        return "Você é um assistente útil e responde em português."


SYSTEM_PROMPT = load_system_prompt()

# Armazena previous_response_id por sessão
conversations: dict[str, str | None] = {}


class ChatRequest(BaseModel):
    message: str
    session_id: str = "default"


class ChatResponse(BaseModel):
    reply: str
    session_id: str


# --- Rota da página HTML ---
@app.get("/", response_class=HTMLResponse)
async def serve_index():
    index_path = BASE_DIR / "static" / "index.html"
    with open(index_path, "r", encoding="utf-8") as f:
        return f.read()


# --- Rota do chat com streaming (SSE) ---
@app.post("/api/chat/stream")
async def chat_stream(req: ChatRequest):
    previous_id = conversations.get(req.session_id)

    # Grava a mensagem do usuário no banco antes de iniciar o stream
    try:
        db.salvar_mensagem(req.session_id, "user", req.message)
    except Exception as e:
        print(f"⚠️ [DB] Falha ao salvar mensagem do usuário: {e}")

    def generate():
        full_reply_parts: list[str] = []
        try:
            params = {
                "model": MODEL,
                "instructions": SYSTEM_PROMPT,
                "input": req.message,
                "reasoning": {"effort": "low"},
                "stream": True,
            }

            # Encadeia com resposta anterior para cache do system prompt
            if previous_id:
                params["previous_response_id"] = previous_id

            stream = client.responses.create(**params)

            response_id = None
            for event in stream:
                # Captura o response ID
                if hasattr(event, "response") and hasattr(event.response, "id"):
                    response_id = event.response.id

                # Envia texto conforme chega
                if event.type == "response.output_text.delta":
                    full_reply_parts.append(event.delta)
                    data = json.dumps({"type": "delta", "text": event.delta})
                    yield f"data: {data}\n\n"

                elif event.type == "response.completed":
                    if event.response and event.response.id:
                        response_id = event.response.id

            # Salva o ID para cache na próxima chamada
            if response_id:
                conversations[req.session_id] = response_id

            # Grava a resposta completa do assistente no banco
            full_reply = "".join(full_reply_parts).strip()
            if full_reply:
                try:
                    db.salvar_mensagem(req.session_id, "assistant", full_reply)
                except Exception as e:
                    print(f"⚠️ [DB] Falha ao salvar resposta do assistente: {e}")

            yield f"data: {json.dumps({'type': 'done'})}\n\n"

        except Exception as e:
            # Tenta salvar o que já foi gerado mesmo em caso de erro
            partial = "".join(full_reply_parts).strip()
            if partial:
                try:
                    db.salvar_mensagem(req.session_id, "assistant", partial + "\n[ERRO: stream interrompido]")
                except Exception:
                    pass
            error_data = json.dumps({"type": "error", "text": str(e)})
            yield f"data: {error_data}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


# --- Rota do chat sem streaming (fallback) ---
@app.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    previous_id = conversations.get(req.session_id)

    # Grava a mensagem do usuário
    try:
        db.salvar_mensagem(req.session_id, "user", req.message)
    except Exception as e:
        print(f"⚠️ [DB] Falha ao salvar mensagem do usuário: {e}")

    try:
        params = {
            "model": MODEL,
            "instructions": SYSTEM_PROMPT,
            "input": req.message,
            "reasoning": {"effort": "low"},
        }
        if previous_id:
            params["previous_response_id"] = previous_id

        response = client.responses.create(**params)
        conversations[req.session_id] = response.id

        # Grava a resposta do assistente
        try:
            db.salvar_mensagem(req.session_id, "assistant", response.output_text)
        except Exception as e:
            print(f"⚠️ [DB] Falha ao salvar resposta do assistente: {e}")

        return ChatResponse(reply=response.output_text, session_id=req.session_id)

    except Exception as e:
        return ChatResponse(reply=f"Erro: {e}", session_id=req.session_id)


# --- Limpar conversa ---
@app.post("/api/clear")
async def clear_session(req: ChatRequest):
    conversations.pop(req.session_id, None)
    return {"status": "ok"}


# --- Status do banco de dados ---
@app.get("/api/db/status")
async def db_status():
    return {"db_enabled": db.db_ativo()}


# --- Monta arquivos estáticos (cria pastas se não existirem) ---
static_dir = BASE_DIR / "static"
if not static_dir.exists():
    static_dir.mkdir(parents=True)
    print(f"📁 Pasta criada: {static_dir}")

pratos_dir = static_dir / "pratos"
if not pratos_dir.exists():
    pratos_dir.mkdir(parents=True)
    print(f"📁 Pasta criada: {pratos_dir}")

app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

print(f"📂 Base dir: {BASE_DIR}")
print(f"📂 Static dir: {static_dir}")
print(f"🍽️ Pratos dir: {pratos_dir}")
print(f"🤖 Modelo: {MODEL}")
print(f"📝 System prompt: {len(SYSTEM_PROMPT)} caracteres")
