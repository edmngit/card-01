import os
import datetime
from typing import Optional
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from dotenv import load_dotenv

_ENGINE: Optional[Engine] = None
_DB_ENABLED = False

def init_db(base_dir: str):
    global _ENGINE, _DB_ENABLED
    
    # Carrega variáveis do arquivo .secret-env
    load_dotenv(os.path.join(base_dir, ".secret-env"))
    
    db_url = os.getenv("DATABASE_URL")
    
    if not db_url:
        print("❌ [DB ERROR] DATABASE_URL não encontrada!")
        _DB_ENABLED = False
        return

    # Ajuste para compatibilidade (postgres:// -> postgresql://)
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)

    try:
        # pool_pre_ping=True ajuda a recuperar conexões perdidas
        _ENGINE = create_engine(db_url, pool_pre_ping=True)
        
        # Teste de conexão simples
        with _ENGINE.connect() as conn:
            conn.execute(text("SELECT 1"))
        
        _DB_ENABLED = True
        print("✅ [DB SUCCESS] Conectado ao PostgreSQL (Schema Public).")
        
        # Chama a criação de tabelas automaticamente ao iniciar
        criar_tabelas()
        
    except Exception as e:
        _DB_ENABLED = False
        print(f"❌ [DB CRITICAL ERROR] Falha ao conectar/inicializar: {e}")

def criar_tabelas():
    """Cria as tabelas no schema public caso não existam."""
    if not _ENGINE: return
    try:
        with _ENGINE.begin() as conn:
            # Criando tabela de sessões
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS sessao_chat (
                    id SERIAL PRIMARY KEY,
                    session_id TEXT UNIQUE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """))
            
            # Criando tabela de mensagens
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS mensagem_chat (
                    id SERIAL PRIMARY KEY,
                    sessao_id INTEGER REFERENCES sessao_chat(id),
                    role TEXT,
                    conteudo TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """))
        print("✅ [DB] Tabelas verificadas/criadas com sucesso.")
    except Exception as e:
        print(f"❌ [DB ERROR] Falha ao criar tabelas: {e}")

def salvar_mensagem(session_id: str, role: str, conteudo: str):
    """Salva a interação no banco de dados."""
    if not _DB_ENABLED or not _ENGINE:
        return

    try:
        with _ENGINE.begin() as conn:
            # 1. Insere a sessão se não existir
            conn.execute(
                text("INSERT INTO sessao_chat (session_id) VALUES (:s) ON CONFLICT (session_id) DO NOTHING"),
                {"s": session_id}
            )
            
            # 2. Busca o ID da sessão
            res = conn.execute(
                text("SELECT id FROM sessao_chat WHERE session_id = :s"),
                {"s": session_id}
            ).fetchone()
            
            # 3. Insere a mensagem vinculada ao ID da sessão
            if res:
                conn.execute(
                    text("INSERT INTO mensagem_chat (sessao_id, role, conteudo) VALUES (:sid, :r, :c)"),
                    {"sid": res[0], "r": role, "c": conteudo}
                )
    except Exception as e:
        print(f"❌ [DB ERROR] Erro ao salvar mensagem: {e}")

def get_engine():
    return _ENGINE

def db_ativo():
    return _DB_ENABLED

def load_system_prompt():
    """Função auxiliar para carregar o prompt (ajuste o caminho se necessário)"""
    try:
        # Assume que o prompt_1.txt está na mesma pasta do main.py
        with open("prompt_1.txt", "r", encoding="utf-8") as f:
            return f.read()
    except:
        return "Você é um assistente prestativo."