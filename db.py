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
    
    _DB_ENABLED    # Garante que as variáveis de ambiente foram carregadas
    load_dotenv(os.path.join(base_dir, ".secret-env"))
    
    db_url = os.getenv("DATABASE_URL")
    
    if not db_url:
        print("❌ [DB ERROR] DATABASE_URL não encontrada!")
        _DB_ENABLED = False
        return

    # Ajuste para compatibilidade do SQLAlchemy com URLs do Heroku/DigitalOcean (postgres:// -> postgresql://)
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)

    try:
        _ENGINE = create_engine(db_url, pool_pre_ping=True)
        # Teste de conexão
        with _ENGINE.connect() as conn:
            conn.execute(text("SELECT 1"))
        
        _DB_ENABLED = True
        print("✅ [DB SUCCESS] Conectado ao PostgreSQL com sucesso.")
        
        # Criação das tabelas se não existirem
    #    criar_tabelas()
        
    except Exception as e:
        _DB_ENABLED = False
        print(f"❌ [DB CRITICAL ERROR] Falha ao conectar/inicializar: {e}")

# def criar_tabelas():
#     if not _ENGINE: return
#     with _ENGINE.begin() as conn:
#         conn.execute(text("CREATE SCHEMA IF NOT EXISTS iasrc;"))
#         conn.execute(text("""
#             CREATE TABLE IF NOT EXISTS iasrc.sessao_chat (
#                 id SERIAL PRIMARY KEY,
#                 session_id TEXT UNIQUE,
#                 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
#             );
#         """))
#         conn.execute(text("""
#             CREATE TABLE IF NOT EXISTS iasrc.mensagem_chat (
#                 id SERIAL PRIMARY KEY,
#                 sessao_id INTEGER REFERENCES iasrc.sessao_chat(id),
#                 role TEXT,
#                 conteudo TEXT,
#                 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
#             );
#         """))

def salvar_mensagem(session_id: str, role: str, conteudo: str):
    if not _DB_ENABLED or not _ENGINE:
        print(f"⚠️ [DB SKIP] Banco inativo. Não salvou: {role}")
        return

    try:
        with _ENGINE.begin() as conn:
            # Garante que a sessão existe
            conn.execute(
                text("INSERT INTO iasrc.sessao_chat (session_id) VALUES (:s) ON CONFLICT (session_id) DO NOTHING"),
                {"s": session_id}
            )
            
            # Pega o ID interno da sessão
            res = conn.execute(
                text("SELECT id FROM iasrc.sessao_chat WHERE session_id = :s"),
                {"s": session_id}
            ).fetchone()
            
            if res:
                id_interno = res[0]
                conn.execute(
                    text("INSERT INTO iasrc.mensagem_chat (sessao_id, role, conteudo) VALUES (:sid, :r, :c)"),
                    {"sid": id_interno, "r": role, "c": conteudo}
                )
    except Exception as e:
        print(f"❌ [DB ERROR] Erro ao salvar mensagem: {e}")

def get_engine():
    return _ENGINE

def db_ativo():
    return 