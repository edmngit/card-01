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

# --- Inicialização Global (FORA de qualquer função ou IF) ---
BASE_DIR = pathlib.Path(__file__).parent
load_dotenv(BASE_DIR / ".secret-env")

# O Uvicorn procura exatamente por esta variável "app"
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
MODEL = "gpt-5-mini"
client = OpenAI(api_key=os.getenv("key"))

class ChatRequest(BaseModel):
    message: str
    session_id: str

# --- Rotas ---

@app.get("/", response_class=HTMLResponse)
async def index():
    with open(BASE_DIR / "index.html", "r", encoding="utf-8") as f:
        return f.read()

@app.post("/api/chat/stream")
async def chat_stream(req: ChatRequest):
    # Salva no banco (agora no public)
    db.salvar_mensagem(req.session_id, "user", req.message)

    def generate():
        full_response = ""
        try:
            # Tenta carregar o prompt do arquivo
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
# Verifique se a pasta 'static' existe para não dar erro ao montar
static_path = BASE_DIR / "static"
if not static_path.exists():
    static_path.mkdir(parents=True)

app.mount("/static", StaticFiles(directory=str(static_path)), name="static")

# O bloco abaixo é só para rodar LOCALMENTE. 
# Na nuvem, o comando de inicialização deve ser: uvicorn main:app --host 0.0.0.0 --port 8080
# ... (restante do código acima igual)

# O bloco abaixo é só para rodar LOCALMENTE. 
if __name__ == "__main__":
    import uvicorn
    # Corrigido: Removido o "080)" e o erro de digitação
    uvicorn.run(app, host="0.0.0.0", port=8080)