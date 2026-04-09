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
        
        # Teste de conexão simples + diagnóstico de usuário/host
        with _ENGINE.connect() as conn:
            conn.execute(text("SELECT 1"))
            info = conn.execute(text("""
                SELECT current_user, current_database(), 
                       inet_server_addr()::text, current_schema()
            """)).fetchone()
            print(f"🔎 [DB DIAG] user={info[0]} db={info[1]} host_addr={info[2]} schema={info[3]}")
        
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

            # Tabela de Feedback dos clientes
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS feedback (
                    id SERIAL PRIMARY KEY,
                    session_id TEXT,
                    tipo TEXT NOT NULL,
                    nome TEXT,
                    mensagem TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """))
            # Índice para acelerar consultas por tipo e data
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_feedback_tipo_data
                ON feedback (tipo, created_at DESC);
            """))
        print("📊 [DB INFO] Verificação de tabelas concluída.")
    except Exception as e:
        print(f"⚠️ [DB WARNING] Erro ao verificar/criar tabelas: {e}")

def salvar_mensagem(session_id: str, role: str, conteudo: str):
    if not _DB_ENABLED or not _ENGINE:
        print(f"⚠️ [DB SKIP] Banco inativo. Mensagem de '{role}' não salva.")
        return

    # Usamos connect() em vez de begin() para ter controle manual se necessário
    with _ENGINE.connect() as conn:
        try:
            # 1. Garante que a sessão existe
            conn.execute(
                text("INSERT INTO sessao_chat (session_id) VALUES (:s) ON CONFLICT (session_id) DO NOTHING"),
                {"s": session_id}
            )
            
            # 2. Busca o ID da sessão
            res = conn.execute(
                text("SELECT id FROM sessao_chat WHERE session_id = :s"),
                {"s": session_id}
            ).fetchone()
            
            if res:
                id_interno = res[0]
                # 3. Insere a mensagem
                conn.execute(
                    text("INSERT INTO mensagem_chat (sessao_id, role, conteudo) VALUES (:sid, :r, :c)"),
                    {"sid": id_interno, "r": role, "c": conteudo}
                )
                # 4. Força a gravação no
                conn.commit()
                print(f"💾 [DB] Mensagem de '{role}' gravada com sucesso!")
            else:
                print(f"❌ [DB] Erro: Não foi possível encontrar/criar a sessão {session_id}")

        except Exception as e:
            conn.rollback()
            print(f"❌ [DB SQL ERROR]: {e}")

            
def get_engine():
    return _ENGINE

def db_ativo():
    """
    Retorna True se o banco de dados estiver conectado e operacional.
    """
    return _DB_ENABLED


def salvar_feedback(session_id: Optional[str], tipo: str, nome: Optional[str], mensagem: str) -> Optional[int]:
    """
    Grava um feedback de cliente no banco.
    tipo: 'elogio' ou 'reclamacao'
    Retorna o id do feedback criado, ou None em caso de falha.
    """
    if not _DB_ENABLED or not _ENGINE:
        print(f"⚠️ [DB SKIP] Banco inativo. Feedback ('{tipo}') não salvo.")
        return None

    if tipo not in ("elogio", "reclamacao"):
        print(f"❌ [DB] Tipo de feedback inválido: {tipo}")
        return None

    if not mensagem or not mensagem.strip():
        print("❌ [DB] Feedback sem mensagem; não gravando.")
        return None

    with _ENGINE.connect() as conn:
        try:
            # Diagnóstico: confirma quem está conectado nesta conexão específica
            who = conn.execute(text("SELECT current_user, current_database()")).fetchone()
            print(f"🔎 [DB DIAG insert feedback] user={who[0]} db={who[1]}")

            res = conn.execute(
                text("""
                    INSERT INTO feedback (session_id, tipo, nome, mensagem)
                    VALUES (:sid, :tipo, :nome, :msg)
                    RETURNING id
                """),
                {
                    "sid": session_id,
                    "tipo": tipo,
                    "nome": (nome or "").strip() or None,
                    "msg": mensagem.strip(),
                },
            ).fetchone()
            conn.commit()
            new_id = res[0] if res else None
            print(f"💾 [DB] Feedback '{tipo}' gravado com sucesso (id={new_id}).")
            return new_id
        except Exception as e:
            conn.rollback()
            print(f"❌ [DB SQL ERROR] salvar_feedback: {e}")
            return None


def listar_feedbacks(limit: int = 100, tipo: Optional[str] = None):
    """
    Retorna os feedbacks mais recentes. Opcionalmente filtra por tipo.
    """
    if not _DB_ENABLED or not _ENGINE:
        return []

    try:
        with _ENGINE.connect() as conn:
            if tipo in ("elogio", "reclamacao"):
                rows = conn.execute(
                    text("""
                        SELECT id, session_id, tipo, nome, mensagem, created_at
                        FROM feedback
                        WHERE tipo = :tipo
                        ORDER BY created_at DESC
                        LIMIT :lim
                    """),
                    {"tipo": tipo, "lim": limit},
                ).fetchall()
            else:
                rows = conn.execute(
                    text("""
                        SELECT id, session_id, tipo, nome, mensagem, created_at
                        FROM feedback
                        ORDER BY created_at DESC
                        LIMIT :lim
                    """),
                    {"lim": limit},
                ).fetchall()

            return [
                {
                    "id": r[0],
                    "session_id": r[1],
                    "tipo": r[2],
                    "nome": r[3],
                    "mensagem": r[4],
                    "created_at": r[5].isoformat() if r[5] else None,
                }
                for r in rows
            ]
    except Exception as e:
        print(f"❌ [DB SQL ERROR] listar_feedbacks: {e}")
        return []


def contar_feedbacks() -> dict:
    """
    Retorna contagem total e por tipo.
    """
    if not _DB_ENABLED or not _ENGINE:
        return {"total": 0, "elogio": 0, "reclamacao": 0}
    try:
        with _ENGINE.connect() as conn:
            row = conn.execute(text("""
                SELECT
                    COUNT(*) AS total,
                    COUNT(*) FILTER (WHERE tipo = 'elogio') AS elogios,
                    COUNT(*) FILTER (WHERE tipo = 'reclamacao') AS reclamacoes
                FROM feedback
            """)).fetchone()
            return {
                "total": int(row[0] or 0),
                "elogio": int(row[1] or 0),
                "reclamacao": int(row[2] or 0),
            }
    except Exception as e:
        print(f"❌ [DB SQL ERROR] contar_feedbacks: {e}")
        return {"total": 0, "elogio": 0, "reclamacao": 0}