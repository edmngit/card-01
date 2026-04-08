import pathlib
import os
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from openai import OpenAI
from dotenv import load_dotenv

# Importar o seu banco de dados corrigido
import db

# --- Inicialização Global ---
BASE_DIR = pathlib.Path(__file__).parent
load_dotenv(BASE_DIR / ".secret-env")

app = FastAPI()

# Inicializa banco de dados
db.init_db(str(BASE_DIR))

# --- Middlewares ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Configuração OpenAI ---
# Alterado para um modelo existente (gpt-4o-mini)
MODEL = "gpt-4o-mini" 
client = OpenAI(api_key=os.getenv("key"))

class ChatRequest(BaseModel):
    message: str
    session_id: str

# --- Rotas ---

@app.get("/", response_class=HTMLResponse)
async def index():
    # CORREÇÃO: Apontando para static/index.html como você mencionou
    html_path = BASE_DIR / "static" / "index.html"
    
    # Caso o arquivo não esteja dentro de static, tenta na raiz por segurança
    if not html_path.exists():
        html_path = BASE_DIR / "index.html"
        
    with open(html_path, "r", encoding="utf-8") as f:
        return f.read()

@app.post("/api/chat/stream")
async def chat_stream(req: ChatRequest):
    db.salvar_mensagem(req.session_id, "user", req.message)

    def generate():
        full_response = ""
        try:
            try:
                with open(BASE_DIR / "prompt_1.txt", "r", encoding="utf-8") as f:
                    system_prompt = f.read()
            except:
                system_prompt = "Você é um assistente prestativo."
            
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

            db.salvar_mensagem(req.session_id, "assistant", full_response)

        except Exception as e:
            yield f"Erro: {str(e)}"

    return StreamingResponse(generate(), media_type="text/event-stream")

# --- Arquivos Estáticos ---
static_path = BASE_DIR / "static"
if not static_path.exists():
    static_path.mkdir(parents=True)

app.mount("/static", StaticFiles(directory=str(static_path)), name="static")

# CORREÇÃO: Removido o erro de sintaxe no final (080)
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)