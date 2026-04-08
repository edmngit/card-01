import os
import datetime
from typing import Optional
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from dotenv import load_dotenv

_ENGINE: Optional[Engine] = None
_DB_ENABLED = False

def init_db(base_dir: str):
    """
    Inicializa a conexão com o banco de dados PostgreSQL.
    """
    global _ENGINE, _DB_ENABLED
    
    # Carrega as variáveis de ambiente do arquivo .secret-env
    load_dotenv(os.path.join(base_dir, ".secret-env"))
    
    db_url = os.getenv("DATABASE_URL")
    
    if not db_url:
        print("❌ [DB ERROR] DATABASE_URL não encontrada nas variáveis de ambiente!")
        _DB_ENABLED = False
        return

    # Ajuste de compatibilidade para URLs do Heroku/DigitalOcean (postgres:// -> postgresql://)
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)

    try:
        # pool_pre_ping=True ajuda a recuperar conexões perdidas automaticamente
        _ENGINE = create_engine(db_url, pool_pre_ping=True)
        
        # Teste de conexão simples
        with _ENGINE.connect() as conn:
            conn.execute(text("SELECT 1"))
        
        _DB_ENABLED = True
        print("✅ [DB SUCCESS] Conectado ao PostgreSQL com sucesso.")
        
        # Garante que as tabelas existam (não afetará se já existirem)
        criar_tabelas()
        
    except Exception as e:
        _DB_ENABLED = False
        print(f"❌ [DB CRITICAL ERROR] Falha ao conectar/inicializar: {e}")

def criar_tabelas():
    """
    Cria a estrutura de tabelas caso ainda não existam no banco.
    """
    if not _ENGINE: 
        return
        
    try:
        with _ENGINE.begin() as conn:
            # Tabela de Sessões
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS sessao_chat (
                    id SERIAL PRIMARY KEY,
                    session_id TEXT UNIQUE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """))
            
            # Tabela de Mensagens
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS mensagem_chat (
                    id SERIAL PRIMARY KEY,
                    sessao_id INTEGER REFERENCES sessao_chat(id),
                    role TEXT,
                    conteudo TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """))
        print("📊 [DB INFO] Verificação de tabelas concluída.")
    except Exception as e:
        print(f"⚠️ [DB WARNING] Erro ao verificar/criar tabelas: {e}")

def salvar_mensagem(session_id: str, role: str, conteudo: str):
    """
    Salva uma mensagem (usuário ou assistente) vinculada a uma sessão.
    """
    if not _DB_ENABLED or not _ENGINE:
        print(f"⚠️ [DB SKIP] Banco inativo ou não conectado. Mensagem de '{role}' não salva.")
        return

    try:
        with _ENGINE.begin() as conn:
            # Garante que a sessão existe no banco
            conn.execute(
                text("INSERT INTO sessao_chat (session_id) VALUES (:s) ON CONFLICT (session_id) DO NOTHING"),
                {"s": session_id}
            )
            
            # Recupera o ID interno da sessão
            res = conn.execute(
                text("SELECT id FROM sessao_chat WHERE session_id = :s"),
                {"s": session_id}
            ).fetchone()
            
            if res:
                id_interno = res[0]
                # Insere a mensagem
                conn.execute(
                    text("INSERT INTO mensagem_chat (sessao_id, role, conteudo) VALUES (:sid, :r, :c)"),
                    {"sid": id_interno, "r": role, "c": conteudo}
                )
    except Exception as e:
        print(f"❌ [DB ERROR] Falha ao salvar mensagem no banco: {e}")

def get_engine():
    return _ENGINE

def db_ativo():
    """
    Retorna True se o banco de dados estiver conectado e operacional.
    """
    return _DB_ENABLED