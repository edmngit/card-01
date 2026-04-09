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


class FeedbackRequest(BaseModel):
    tipo: str  # 'elogio' ou 'reclamacao'
    mensagem: str
    nome: str | None = None
    session_id: str | None = None


class PedidoItemIn(BaseModel):
    nome: str
    quantidade: int = 1
    preco_unitario: float = 0
    observacao: str | None = None


class PedidoCreateRequest(BaseModel):
    session_id: str
    items: list[PedidoItemIn]
    total_estimado: float = 0
    total_com_servico: float = 0


class PedidoUpdateRequest(BaseModel):
    status: str | None = None  # 'pendente' | 'confirmado' | 'cancelado'
    garcom_nome: str | None = None
    garcom_obs: str | None = None
    items_qty_final: dict[str, int] | None = None  # { "<item_id>": qty_final }


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


# --- Feedback dos clientes ---
@app.post("/api/feedback")
async def criar_feedback(req: FeedbackRequest):
    tipo = (req.tipo or "").strip().lower()
    if tipo not in ("elogio", "reclamacao"):
        return {"ok": False, "error": "Tipo inválido. Use 'elogio' ou 'reclamacao'."}

    mensagem = (req.mensagem or "").strip()
    if len(mensagem) < 3:
        return {"ok": False, "error": "Mensagem muito curta."}

    if not db.db_ativo():
        return {"ok": False, "error": "Banco de dados indisponível no momento."}

    new_id = db.salvar_feedback(
        session_id=req.session_id,
        tipo=tipo,
        nome=req.nome,
        mensagem=mensagem,
    )
    if new_id is None:
        return {"ok": False, "error": "Falha ao gravar o feedback."}

    return {"ok": True, "id": new_id}


@app.get("/api/feedback")
async def listar_feedback(tipo: str | None = None, limit: int = 100):
    return {
        "items": db.listar_feedbacks(limit=limit, tipo=tipo),
        "stats": db.contar_feedbacks(),
    }


# ============================================================
# PEDIDOS
# ============================================================

@app.post("/api/pedidos")
async def criar_pedido(req: PedidoCreateRequest):
    """Cliente envia um pedido para a cozinha (status inicial: pendente)."""
    if not db.db_ativo():
        return {"ok": False, "error": "Banco de dados indisponível no momento."}

    if not req.session_id or not req.items:
        return {"ok": False, "error": "session_id e items são obrigatórios."}

    items_payload = [
        {
            "nome": it.nome,
            "quantidade": it.quantidade,
            "preco_unitario": it.preco_unitario,
            "observacao": it.observacao,
        }
        for it in req.items
    ]

    pedido = db.criar_pedido(
        session_id=req.session_id,
        items=items_payload,
        total_estimado=req.total_estimado,
        total_com_servico=req.total_com_servico,
    )
    if not pedido:
        return {"ok": False, "error": "Falha ao criar pedido."}
    return {"ok": True, "pedido": pedido}


@app.get("/api/pedidos")
async def listar_pedidos(
    status: str | None = None,
    session_id: str | None = None,
    limit: int = 200,
):
    """
    Lista pedidos. Filtros opcionais:
      - status=pendente|confirmado|cancelado
      - session_id=<id>  (para a aba 'Pedidos' do cliente)
    """
    if not db.db_ativo():
        return {"ok": False, "error": "Banco de dados indisponível.", "items": []}
    items = db.listar_pedidos(status=status, session_id=session_id, limit=limit)
    return {"ok": True, "items": items}


@app.get("/api/pedidos/{pedido_id}")
async def obter_pedido(pedido_id: int):
    if not db.db_ativo():
        return {"ok": False, "error": "Banco de dados indisponível."}
    p = db.obter_pedido(pedido_id)
    if not p:
        return {"ok": False, "error": "Pedido não encontrado."}
    return {"ok": True, "pedido": p}


@app.patch("/api/pedidos/{pedido_id}")
async def atualizar_pedido(pedido_id: int, req: PedidoUpdateRequest):
    """
    Endpoint usado pelo garçom para aprovar (confirmado),
    rejeitar (cancelado) ou alterar quantidades de um pedido.
    """
    if not db.db_ativo():
        return {"ok": False, "error": "Banco de dados indisponível."}

    if req.status and req.status not in ("pendente", "confirmado", "cancelado"):
        return {"ok": False, "error": "Status inválido."}

    pedido = db.atualizar_pedido_garcom(
        pedido_id=pedido_id,
        status=req.status,
        garcom_nome=(req.garcom_nome or None),
        garcom_obs=(req.garcom_obs if req.garcom_obs is not None else None),
        items_qty_final=req.items_qty_final or None,
    )
    if not pedido:
        return {"ok": False, "error": "Falha ao atualizar o pedido."}
    return {"ok": True, "pedido": pedido}


# ============================================================
# ADMIN
# ============================================================

@app.get("/api/admin/stats")
async def admin_stats():
    """Estatísticas para o painel admin."""
    if not db.db_ativo():
        return {"ok": False, "error": "Banco de dados indisponível."}
    return {"ok": True, "stats": db.estatisticas_admin()}


@app.get("/api/admin/queries")
async def admin_queries(limit: int = 50):
    """Consultas (mensagens de usuários) recentes para o painel admin."""
    if not db.db_ativo():
        return {"ok": False, "error": "Banco de dados indisponível.", "items": []}
    return {"ok": True, "items": db.listar_consultas_recentes(limit=limit)}


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
