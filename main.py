"""
FastAPI Backend - Chat com OpenAI + Fotos de Pratos via System Prompt
Modificado para persistência de dados no PostgreSQL e visualização com HTMX.
"""
import pathlib
import json
import os
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from openai import OpenAI
from dotenv import load_dotenv

# Importando o módulo de banco de dados
import db

# --- Caminho base (pasta onde está o main.py) ---
BASE_DIR = pathlib.Path(__file__).parent

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Carrega variáveis e inicializa o banco de dados Postgres
load_dotenv(BASE_DIR / ".secret-env")
db.init_db(str(BASE_DIR))

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


# --- Rota da página HTML Principal ---
@app.get("/", response_class=HTMLResponse)
async def serve_index():
    index_path = BASE_DIR / "static" / "index.html"
    try:
        with open(index_path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return "<h1>Arquivo index.html não encontrado na pasta static.</h1>"


# --- Rota do chat com streaming (SSE) ---
@app.post("/api/chat/stream")
async def chat_stream(req: ChatRequest):
    previous_id = conversations.get(req.session_id)
    
    # 💾 BANCO: Salva a mensagem do usuário
    db.salvar_mensagem(req.session_id, "user", req.message)

    def generate():
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
            accumulated_text = ""
            
            for event in stream:
                # Captura o response ID
                if hasattr(event, "response") and hasattr(event.response, "id"):
                    response_id = event.response.id

                # Envia texto conforme chega
                if event.type == "response.output_text.delta":
                    accumulated_text += event.delta
                    data = json.dumps({"type": "delta", "text": event.delta})
                    yield f"data: {data}\n\n"

                elif event.type == "response.completed":
                    if event.response and event.response.id:
                        response_id = event.response.id

            # Salva o ID para cache na próxima chamada
            if response_id:
                conversations[req.session_id] = response_id

            # 💾 BANCO: Salva a resposta completa gerada pela IA
            if accumulated_text:
                db.salvar_mensagem(req.session_id, "assistant", accumulated_text)

            yield f"data: {json.dumps({'type': 'done'})}\n\n"

        except Exception as e:
            error_data = json.dumps({"type": "error", "text": str(e)})
            yield f"data: {error_data}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


# --- Rota do chat sem streaming (fallback) ---
@app.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    previous_id = conversations.get(req.session_id)

    # 💾 BANCO: Salva a mensagem do usuário
    db.salvar_mensagem(req.session_id, "user", req.message)

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

        # 💾 BANCO: Salva a resposta da IA
        db.salvar_mensagem(req.session_id, "assistant", response.output_text)

        return ChatResponse(reply=response.output_text, session_id=req.session_id)

    except Exception as e:
        return ChatResponse(reply=f"Erro: {e}", session_id=req.session_id)


# --- Limpar conversa ---
@app.post("/api/clear")
async def clear_session(req: ChatRequest):
    conversations.pop(req.session_id, None)
    return {"status": "ok"}


# ==============================================================================
# --- ROTAS ADMINISTRATIVAS (HTMX + BOOTSTRAP) ---
# ==============================================================================

@app.get("/admin", response_class=HTMLResponse)
async def admin_page():
    """Página principal do Admin usando Bootstrap e HTMX."""
    html_content = """
    <!DOCTYPE html>
    <html lang="pt-BR">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Painel de Análise - Chat</title>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
        <script src="https://unpkg.com/htmx.org@1.9.10"></script>
        <style>
            .msg-user { background-color: #e9ecef; border-radius: 10px; padding: 10px; margin-bottom: 10px; }
            .msg-assistant { background-color: #d1e7dd; border-radius: 10px; padding: 10px; margin-bottom: 10px; }
        </style>
    </head>
    <body class="bg-light">
        <div class="container mt-5">
            <div class="row">
                <div class="col-12 mb-4">
                    <h1 class="text-primary">Análise de Conversas</h1>
                    <p class="text-muted">Acompanhe as interações dos usuários com o sistema em tempo real.</p>
                </div>
            </div>
            
            <div class="row">
                <div class="col-md-4">
                    <div class="card shadow-sm">
                        <div class="card-header bg-dark text-white d-flex justify-content-between align-items-center">
                            Conversas Ativas
                            <button class="btn btn-sm btn-outline-light" hx-get="/admin/sessoes" hx-target="#lista-sessoes">Atualizar</button>
                        </div>
                        <div class="list-group list-group-flush" id="lista-sessoes" hx-get="/admin/sessoes" hx-trigger="load">
                            <div class="p-3 text-center">Carregando sessões...</div>
                        </div>
                    </div>
                </div>
                
                <div class="col-md-8">
                    <div class="card shadow-sm">
                        <div class="card-header bg-primary text-white">
                            Visualização do Diálogo
                        </div>
                        <div class="card-body" id="conteudo-conversa" style="min-height: 400px; max-height: 600px; overflow-y: auto;">
                            <div class="text-center text-muted mt-5">
                                Selecione uma sessão ao lado para ver o histórico de mensagens.
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </body>
    </html>
    """
    return html_content


@app.get("/admin/sessoes", response_class=HTMLResponse)
async def admin_lista_sessoes():
    """Componente HTMX que retorna a lista de sessões do Postgres."""
    # Usaremos uma consulta direta via text no SQLAlchemy
    from sqlalchemy import text
    
    if not db._DB_ENABLED:
        return "<div class='p-3 text-danger'>Banco de dados desativado ou sem conexão!</div>"
        
    try:
        engine = db.get_engine()
        with engine.connect() as conn:
            query = text("SELECT id, session_id, created_at FROM iasrc.sessao_chat ORDER BY created_at DESC LIMIT 50")
            result = conn.execute(query).fetchall()
            
            if not result:
                return "<div class='p-3 text-center text-muted'>Nenhuma sessão encontrada.</div>"
                
            html = ""
            for row in result:
                id_interno, sess_id, data = row
                data_formatada = data.strftime("%d/%m/%Y %H:%M")
                html += f"""
                <button class="list-group-item list-group-item-action" 
                        hx-get="/admin/sessoes/{id_interno}" 
                        hx-target="#conteudo-conversa"
                        hx-swap="innerHTML">
                    <div class="d-flex w-100 justify-content-between">
                        <h6 class="mb-1 text-truncate" style="max-width: 150px;">{sess_id}</h6>
                        <small class="text-muted">{data_formatada}</small>
                    </div>
                    <small class="text-muted">ID Banco: {id_interno}</small>
                </button>
                """
            return html
    except Exception as e:
        return f"<div class='p-3 text-danger'>Erro ao buscar sessões: {e}</div>"


@app.get("/admin/sessoes/{id_interno}", response_class=HTMLResponse)
async def admin_mensagens_sessao(id_interno: int):
    """Componente HTMX que retorna o histórico de uma conversa específica."""
    from sqlalchemy import text
    
    if not db._DB_ENABLED:
        return "<div class='text-danger'>Banco de dados desativado.</div>"
        
    try:
        engine = db.get_engine()
        with engine.connect() as conn:
            query = text("""
                SELECT role, conteudo, created_at 
                FROM iasrc.mensagem_chat 
                WHERE sessao_id = :id_interno 
                ORDER BY created_at ASC
            """)
            result = conn.execute(query, {"id_interno": id_interno}).fetchall()
            
            if not result:
                return "<div class='text-center text-muted mt-5'>Nenhuma mensagem nesta sessão.</div>"
                
            html = ""
            for row in result:
                role, conteudo, data = row
                data_fmt = data.strftime("%H:%M:%S")
                
                classe_msg = "msg-user" if role == "user" else "msg-assistant"
                autor = "Você" if role == "user" else "Inteligência Artificial"
                
                html += f"""
                <div class="{classe_msg} shadow-sm">
                    <div class="d-flex justify-content-between border-bottom pb-1 mb-2">
                        <strong>{autor}</strong>
                        <small class="text-muted">{data_fmt}</small>
                    </div>
                    <div style="white-space: pre-wrap;">{conteudo}</div>
                </div>
                """
            return html
    except Exception as e:
        return f"<div class='text-danger'>Erro ao carregar mensagens: {e}</div>"

# ==============================================================================


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