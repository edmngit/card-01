import pathlib
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from openai import OpenAI
import os
from dotenv import load_dotenv

# Importar suas funções de banco de dados
import db

BASE_DIR = pathlib.Path(__file__).parent
load_dotenv(BASE_DIR / ".secret-env")

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Configurações ---
MODEL = "gpt-5-mini" # Certifique-se que o nome do modelo está correto para sua conta
client = OpenAI(api_key=os.getenv("key"))

# Inicializa o DB (Cria as tabelas no 'public' se não existirem)
db.init_db(str(BASE_DIR))
db.criar_tabelas()

class ChatRequest(BaseModel):
    message: str
    session_id: str

@app.get("/", response_class=HTMLResponse)
async def index():
    with open(BASE_DIR / "index.html", "r", encoding="utf-8") as f:
        return f.read()

@app.post("/api/chat/stream")
async def chat_stream(req: ChatRequest):
    # 1. Salva a pergunta do usuário no banco (agora no schema public)
    db.salvar_mensagem(req.session_id, "user", req.message)

    def generate():
        full_response = ""
        try:
            # Carrega o prompt (certifique-se que load_system_prompt está no seu main ou db)
            system_prompt = db.load_system_prompt() 
            
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
                    yield content

            # 2. Salva a resposta da IA no banco
            db.salvar_mensagem(req.session_id, "assistant", full_response)

        except Exception as e:
            yield f"Erro: {str(e)}"

    return StreamingResponse(generate(), media_type="text/event-stream")

# --- Rota de Admin (Se você tiver um dashboard) ---
@app.get("/api/admin/queries")
async def get_admin_queries():
    # Certifique-se que dentro de db.obter_historico não existe "iasrc."
    return db.obter_historico_admin() 

# --- Arquivos Estáticos ---
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)