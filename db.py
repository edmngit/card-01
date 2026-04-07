import os
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from dotenv import load_dotenv

_ENGINE = None
_DB_ENABLED = False

def init_db(base_dir):
    global _ENGINE, _DB_ENABLED
    load_dotenv(os.path.join(base_dir, '.secret-env'))
    
    # A DigitalOcean injeta a DATABASE_URL automaticamente se configurada no painel
    db_url = os.getenv("DATABASE_URL")
    
    if not db_url:
        print("❌ [DB ERROR] DATABASE_URL não encontrada nas variáveis de ambiente!")
        return

    # O SQLAlchemy exige 'postgresql://', mas a DO às vezes envia 'postgres://'
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)

    try:
        # Criando o motor de conexão
        _ENGINE = create_engine(
            db_url,
            pool_pre_ping=True,
            connect_args={"sslmode": "require"} # Força o SSL exigido pela DO
        )
        
        # Teste real de escrita e criação de tabelas
        with _ENGINE.begin() as conn:
            print("🔍 [DB] Verificando/Criando Schema e Tabelas...")
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
                    sessao_id INT REFERENCES iasrc.sessao_chat(id),
                    role VARCHAR(20),
                    conteudo TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """))
        
        _DB_ENABLED = True
        print("✅ [DB SUCCESS] Conectado e tabelas prontas!")
    except Exception as e:
        _DB_ENABLED = False
        print(f"❌ [DB CRITICAL ERROR] Falha ao iniciar banco: {str(e)}")

def salvar_mensagem(session_id, role, conteudo):
    if not _DB_ENABLED:
        print(f"⚠️ [DB SKIP] Tentativa de salvar {role}, mas banco está desativado.")
        return
    
    try:
        with _ENGINE.begin() as conn:
            # 1. Garante a sessão (Upsert)
            res = conn.execute(text("""
                INSERT INTO iasrc.sessao_chat (session_id) 
                VALUES (:s_id) 
                ON CONFLICT (session_id) DO UPDATE SET session_id = EXCLUDED.session_id
                RETURNING id
            """), {"s_id": session_id})
            internal_id = res.scalar()

            # 2. Insere a mensagem
            conn.execute(text("""
                INSERT INTO iasrc.mensagem_chat (sessao_id, role, conteudo) 
                VALUES (:sid, :role, :cont)
            """), {"sid": internal_id, "role": role, "cont": conteudo})
            print(f"💾 [DB] Mensagem de '{role}' salva para sessão {session_id}")
    except Exception as e:
        print(f"❌ [DB ERROR] Erro ao salvar mensagem: {str(e)}")