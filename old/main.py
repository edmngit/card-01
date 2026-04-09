import pathlib
import os
import json
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from openai import OpenAI
from dotenv import load_dotenv

# Importar o seu banco de dados
import db

# --- Inicialização Global ---
BASE_DIR = pathlib.Path(__file__).parent
# Carrega as variáveis de ambiente do arquivo .secret-env
load_dotenv(BASE_DIR / ".secret-env")

app = FastAPI()

# Inicializa banco de dados conectando ao PostgreSQL e criando tabelas
db.init_db(str(BASE_DIR))

# --- Middlewares ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Configuração OpenAI ---
# Modelo definido como gpt-4o-mini
MODEL = "gpt-4o-mini" 
# A chave da API é lida da variável 'key' no arquivo .secret-env
client = OpenAI(api_key=os.getenv("key"))

class ChatRequest(BaseModel):
    message: str
    session_id: str

# --- Rotas ---

@app.get("/", response_class=HTMLResponse)
async def index():
    # Tenta localizar o index.html na pasta static ou na raiz
    html_path = BASE_DIR / "static" / "index.html"
    if not html_path.exists():
        html_path = BASE_DIR / "index.html"
        
    with open(html_path, "r", encoding="utf-8") as f:
        return f.read()

@app.get("/api/debug/db")
async def debug_db():
    from sqlalchemy import text
    with db.get_engine().connect() as conn:
        res = conn.execute(text("SELECT COUNT(*) FROM mensagem_chat")).fetchone()
        return {"total_mensagens_no_banco": res[0]}

@app.get("/api/debug/db-name")
async def debug_db_name():
    from sqlalchemy import text
    with db.get_engine().connect() as conn:
        # Este comando pergunta ao banco de dados: "Em qual banco estou agora?"
        res = conn.execute(text("SELECT current_database()")).fetchone()
        return {"banco_conectado_atualmente": res[0]}

@app.post("/api/chat/stream")
async def chat_stream(req: ChatRequest):
    # Salva a mensagem do usuário no banco de dados
    db.salvar_mensagem(req.session_id, "user", req.message)

    def generate():
        full_response = ""
        try:
            # Tenta carregar o prompt de sistema de um arquivo externo
            try:
                with open(BASE_DIR / "prompt_1.txt", "r", encoding="utf-8") as f:
                    system_prompt = f.read()
            except:
                system_prompt = "Você é um assistente prestativo da Divina Comida."
            
            # Inicia a chamada ao modelo com streaming habilitado
            stream = client.chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": req.message}
                ],
                stream=True,
            )
            
            for chunk in stream:
                content = chunk.choices[0].delta.content
                if content:
                    full_response += content
                    # Formata o chunk como JSON dentro do padrão SSE para o index.html ler
                    data = json.dumps({"type": "delta", "text": content})
                    yield f"data: {data}\n\n"

            # Salva a resposta completa do assistente no banco
            db.salvar_mensagem(req.session_id, "assistant", full_response)
            
            # Envia o sinal de finalização esperado pelo frontend
            yield f"data: {json.dumps({'type': 'done'})}\n\n"

        except Exception as e:
            # Envia erro formatado para o frontend
            error_msg = json.dumps({"type": "error", "text": str(e)})
            yield f"data: {error_msg}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")

# Rota para limpar o histórico da sessão (chamada pelo botão de lixeira no index.html)
@app.post("/api/clear")
async def clear_session(req: dict):
    session_id = req.get("session_id")
    if session_id:
        # Aqui você pode implementar a limpeza lógica no banco se desejar
        print(f"Solicitação de limpeza para a sessão: {session_id}")
    return {"status": "ok"}

# --- Arquivos Estáticos ---
static_path = BASE_DIR / "static"
if not static_path.exists():
    static_path.mkdir(parents=True)

app.mount("/static", StaticFiles(directory=str(static_path)), name="static")

if __name__ == "__main__":
    import uvicorn
    # Servidor rodando na porta 8080
    uvicorn.run(app, host="0.0.0.0", port=8080)