import os
from typing import Optional
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from dotenv import load_dotenv

_ENGINE: Optional[Engine] = None
_DB_ENABLED = False

def init_db(base_dir: str) -> None:
    """Inicializa a conexão com o PostgreSQL usando DATABASE_URL da Digital Ocean."""
    global _ENGINE, _DB_ENABLED
    
    # Tenta carregar do ficheiro local se existir, senão usa o ambiente do sistema
    load_dotenv(os.path.join(base_dir, '.secret-env'))
    
    db_url = os.getenv("DATABASE_URL")
    
    if not db_url:
        print("⚠️ DATABASE_URL não encontrada. O registo de mensagens estará desativado.")
        _DB_ENABLED = False
        return

    try:
        # Correção obrigatória: SQLAlchemy exige 'postgresql://' em vez de 'postgres://'
        if db_url.startswith("postgres://"):
            db_url = db_url.replace("postgres://", "postgresql://", 1)

        # Configuração do Engine com Pool de ligações para estabilidade
        _ENGINE = create_engine(
            db_url,
            pool_pre_ping=True,
            pool_recycle=1800
        )
        
        # Criação automática da estrutura de tabelas
        with _ENGINE.begin() as conn:
            conn.execute(text("CREATE SCHEMA IF NOT EXISTS iasrc;"))
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS iasrc.sessao_chat (
                    id SERIAL PRIMARY KEY,
                    session_id VARCHAR(255) UNIQUE NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """))
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS iasrc.mensagem_chat (
                    id SERIAL PRIMARY KEY,
                    sessao_id INT REFERENCES iasrc.sessao_chat(id) ON DELETE CASCADE,
                    role VARCHAR(20) NOT NULL,
                    conteudo TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """))
            
        _DB_ENABLED = True
        print("✅ Base de Dados PostgreSQL ligada e tabelas verificadas!")
    except Exception as e:
        _DB_ENABLED = False
        print(f"❌ Erro Crítico na Base de Dados: {e}")

def get_engine() -> Engine:
    if not _DB_ENABLED or _ENGINE is None:
        raise RuntimeError('A base de dados não está ativa.')
    return _ENGINE

def salvar_mensagem(session_id: str, role: str, conteudo: str):
    """Guarda a interação no banco de dados."""
    if not _DB_ENABLED:
        return
        
    try:
        engine = get_engine()
        with engine.begin() as conn:
            # Obtém ou cria a sessão e retorna o ID interno
            stmt_sess = text("""
                INSERT INTO iasrc.sessao_chat (session_id) 
                VALUES (:s_id) 
                ON CONFLICT (session_id) DO UPDATE SET session_id = EXCLUDED.session_id
                RETURNING id
            """)
            result = conn.execute(stmt_sess, {"s_id": session_id})
            sess_id_interno = result.scalar()
            
            # Insere a mensagem (User ou Assistant)
            stmt_msg = text("""
                INSERT INTO iasrc.mensagem_chat (sessao_id, role, conteudo) 
                VALUES (:sid, :role, :cont)
            """)
            conn.execute(stmt_msg, {
                "sid": sess_id_interno, 
                "role": role, 
                "cont": conteudo
            })
    except Exception as e:
        print(f"⚠️ Erro ao gravar mensagem: {e}")