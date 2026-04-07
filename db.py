import os
import datetime
from typing import Optional
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from dotenv import load_dotenv

_ENGINE: Optional[Engine] = None
_DB_ENABLED = False

def init_db(base_dir: str) -> None:
    """Inicializa a conexão com o PostgreSQL usando variáveis de ambiente."""
    global _ENGINE, _DB_ENABLED
    
    # Carrega o arquivo de segredos
    load_dotenv(os.path.join(base_dir, '.secret-env'))
    
    # Monta a string de conexão para PostgreSQL
    # Formato esperado: postgresql://usuario:senha@host:porta/db-dados
    db_url = os.getenv("DATABASE_URL")
    
    if not db_url:
        print("⚠️ DATABASE_URL não encontrada no .secret-env")
        _DB_ENABLED = False
        return

    try:
        # Usando psycopg2 como driver padrão para Postgres
        _ENGINE = create_engine(
            db_url,
            pool_pre_ping=True,
            pool_recycle=1800,
            pool_size=5,
            max_overflow=10
        )
        
        # Teste rápido
        with _ENGINE.connect() as conn:
            conn.execute(text("SELECT 1"))
            
        _DB_ENABLED = True
        print("✅ Conexão com o PostgreSQL (db-dados) estabelecida com sucesso!")
    except Exception as e:
        _DB_ENABLED = False
        print(f"⚠️ Erro ao conectar no PostgreSQL: {e}")

def get_engine() -> Engine:
    if not _DB_ENABLED or _ENGINE is None:
        raise RuntimeError('Banco de dados não está ativo ou não foi inicializado.')
    return _ENGINE

def salvar_mensagem(session_id: str, role: str, conteudo: str):
    """Salva a mensagem no banco, criando a sessão se ela não existir."""
    if not _DB_ENABLED:
        return
        
    engine = get_engine()
    
    try:
        with engine.begin() as conn:
            # 1. Tenta buscar o ID da sessão
            sql_sessao = text("SELECT id FROM iasrc.sessao_chat WHERE session_id = :session_id")
            result = conn.execute(sql_sessao, {"session_id": session_id}).fetchone()
            
            if result:
                sessao_internal_id = result[0]
            else:
                # Se não existe, cria a sessão
                sql_insert_sessao = text(
                    "INSERT INTO iasrc.sessao_chat (session_id) VALUES (:session_id) RETURNING id"
                )
                res_insert = conn.execute(sql_insert_sessao, {"session_id": session_id})
                sessao_internal_id = res_insert.fetchone()[0]
            
            # 2. Insere a mensagem vinculada à sessão
            sql_msg = text(
                "INSERT INTO iasrc.mensagem_chat (sessao_id, role, conteudo) "
                "VALUES (:sessao_id, :role, :conteudo)"
            )
            conn.execute(sql_msg, {
                "sessao_id": sessao_internal_id,
                "role": role,
                "conteudo": conteudo
            })
            
    except Exception as e:
        print(f"⚠️ Erro ao salvar mensagem no banco: {e}")