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

            # ============================================================
            # PEDIDOS
            # ============================================================
            # Sequência de numeração diária dos pedidos (ex: #001, #002...)
            conn.execute(text("""
                CREATE SEQUENCE IF NOT EXISTS pedido_numero_seq START 1;
            """))

            # Tabela principal de pedidos
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS pedido (
                    id SERIAL PRIMARY KEY,
                    numero INTEGER NOT NULL DEFAULT nextval('pedido_numero_seq'),
                    session_id TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pendente',
                    total_estimado NUMERIC(10,2) NOT NULL DEFAULT 0,
                    total_com_servico NUMERIC(10,2) NOT NULL DEFAULT 0,
                    total_final NUMERIC(10,2),
                    garcom_nome TEXT,
                    garcom_obs TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """))

            # Itens do pedido
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS pedido_item (
                    id SERIAL PRIMARY KEY,
                    pedido_id INTEGER NOT NULL REFERENCES pedido(id) ON DELETE CASCADE,
                    nome TEXT NOT NULL,
                    quantidade INTEGER NOT NULL DEFAULT 1,
                    qty_final INTEGER NOT NULL DEFAULT 1,
                    preco_unitario NUMERIC(10,2) NOT NULL DEFAULT 0,
                    observacao TEXT,
                    posicao INTEGER NOT NULL DEFAULT 0
                );
            """))

            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_pedido_status ON pedido(status, created_at DESC);
            """))
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_pedido_session ON pedido(session_id, created_at DESC);
            """))
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_pedido_item_pedido ON pedido_item(pedido_id);
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

# ============================================================
# PEDIDOS
# ============================================================

def criar_pedido(session_id: str, items: list, total_estimado: float, total_com_servico: float) -> Optional[dict]:
    """
    Cria um pedido com seus itens. Retorna o pedido criado (com id e número) ou None.
    items: lista de dicts com keys: nome, quantidade, preco_unitario, observacao (opcional)
    """
    if not _DB_ENABLED or not _ENGINE:
        print("⚠️ [DB SKIP] Banco inativo. Pedido não salvo.")
        return None

    if not session_id or not items:
        print("❌ [DB] Pedido inválido (sem session_id ou itens).")
        return None

    with _ENGINE.connect() as conn:
        try:
            res = conn.execute(
                text("""
                    INSERT INTO pedido (session_id, status, total_estimado, total_com_servico)
                    VALUES (:sid, 'pendente', :te, :ts)
                    RETURNING id, numero, created_at
                """),
                {"sid": session_id, "te": total_estimado, "ts": total_com_servico},
            ).fetchone()

            if not res:
                conn.rollback()
                return None

            pedido_id = res[0]
            numero = res[1]
            created_at = res[2]

            for idx, it in enumerate(items):
                qtd = int(it.get("quantidade") or 1)
                conn.execute(
                    text("""
                        INSERT INTO pedido_item
                            (pedido_id, nome, quantidade, qty_final, preco_unitario, observacao, posicao)
                        VALUES (:pid, :nome, :qtd, :qtd, :preco, :obs, :pos)
                    """),
                    {
                        "pid": pedido_id,
                        "nome": (it.get("nome") or "").strip(),
                        "qtd": qtd,
                        "preco": float(it.get("preco_unitario") or 0),
                        "obs": (it.get("observacao") or "").strip() or None,
                        "pos": idx,
                    },
                )

            conn.commit()
            print(f"💾 [DB] Pedido #{numero:03d} (id={pedido_id}) criado com {len(items)} item(ns).")
            return obter_pedido(pedido_id)
        except Exception as e:
            conn.rollback()
            print(f"❌ [DB SQL ERROR] criar_pedido: {e}")
            return None


def obter_pedido(pedido_id: int) -> Optional[dict]:
    """Retorna um pedido completo com seus itens, ou None."""
    if not _DB_ENABLED or not _ENGINE:
        return None
    try:
        with _ENGINE.connect() as conn:
            row = conn.execute(
                text("""
                    SELECT id, numero, session_id, status, total_estimado, total_com_servico,
                           total_final, garcom_nome, garcom_obs, created_at, updated_at
                    FROM pedido WHERE id = :id
                """),
                {"id": pedido_id},
            ).fetchone()
            if not row:
                return None

            items = conn.execute(
                text("""
                    SELECT id, nome, quantidade, qty_final, preco_unitario, observacao, posicao
                    FROM pedido_item WHERE pedido_id = :pid ORDER BY posicao ASC, id ASC
                """),
                {"pid": pedido_id},
            ).fetchall()

            return _pedido_to_dict(row, items)
    except Exception as e:
        print(f"❌ [DB SQL ERROR] obter_pedido: {e}")
        return None


def listar_pedidos(status: Optional[str] = None, session_id: Optional[str] = None, limit: int = 200) -> list:
    """Lista pedidos opcionalmente filtrados por status e/ou sessão. Inclui itens."""
    if not _DB_ENABLED or not _ENGINE:
        return []
    try:
        with _ENGINE.connect() as conn:
            where = []
            params: dict = {"lim": limit}
            if status:
                where.append("status = :status")
                params["status"] = status
            if session_id:
                where.append("session_id = :sid")
                params["sid"] = session_id
            where_sql = ("WHERE " + " AND ".join(where)) if where else ""

            rows = conn.execute(
                text(f"""
                    SELECT id, numero, session_id, status, total_estimado, total_com_servico,
                           total_final, garcom_nome, garcom_obs, created_at, updated_at
                    FROM pedido
                    {where_sql}
                    ORDER BY created_at DESC
                    LIMIT :lim
                """),
                params,
            ).fetchall()

            if not rows:
                return []

            ids = [r[0] for r in rows]
            items_rows = conn.execute(
                text("""
                    SELECT id, pedido_id, nome, quantidade, qty_final, preco_unitario, observacao, posicao
                    FROM pedido_item
                    WHERE pedido_id = ANY(:ids)
                    ORDER BY pedido_id ASC, posicao ASC, id ASC
                """),
                {"ids": ids},
            ).fetchall()

            items_by_pedido: dict = {}
            for ir in items_rows:
                items_by_pedido.setdefault(ir[1], []).append(
                    (ir[0], ir[2], ir[3], ir[4], ir[5], ir[6], ir[7])
                )

            result = []
            for r in rows:
                its = items_by_pedido.get(r[0], [])
                # Ajusta forma para _pedido_to_dict (que espera tuplas com índices [0..6])
                result.append(_pedido_to_dict(r, its))
            return result
    except Exception as e:
        print(f"❌ [DB SQL ERROR] listar_pedidos: {e}")
        return []


def atualizar_pedido_garcom(
    pedido_id: int,
    status: Optional[str] = None,
    garcom_nome: Optional[str] = None,
    garcom_obs: Optional[str] = None,
    items_qty_final: Optional[dict] = None,  # { item_id: qty_final }
) -> Optional[dict]:
    """
    Atualiza um pedido (ação do garçom). Pode mudar status, gravar nome/obs e
    atualizar quantidades finais dos itens. Retorna o pedido atualizado.
    """
    if not _DB_ENABLED or not _ENGINE:
        return None

    if status and status not in ("pendente", "confirmado", "cancelado"):
        print(f"❌ [DB] Status inválido: {status}")
        return None

    with _ENGINE.connect() as conn:
        try:
            # Atualiza quantidades dos itens primeiro
            if items_qty_final:
                for item_id, qf in items_qty_final.items():
                    try:
                        qf_int = max(0, int(qf))
                    except (TypeError, ValueError):
                        continue
                    conn.execute(
                        text("""
                            UPDATE pedido_item
                            SET qty_final = :q
                            WHERE id = :iid AND pedido_id = :pid
                        """),
                        {"q": qf_int, "iid": int(item_id), "pid": pedido_id},
                    )

            # Atualiza campos do pedido
            sets = ["updated_at = CURRENT_TIMESTAMP"]
            params: dict = {"pid": pedido_id}
            if status is not None:
                sets.append("status = :status")
                params["status"] = status
            if garcom_nome is not None:
                sets.append("garcom_nome = :gn")
                params["gn"] = garcom_nome
            if garcom_obs is not None:
                sets.append("garcom_obs = :go")
                params["go"] = garcom_obs

            conn.execute(
                text(f"UPDATE pedido SET {', '.join(sets)} WHERE id = :pid"),
                params,
            )

            # Se o status mudou para confirmado, recalcula o total_final a partir dos itens
            if status == "confirmado":
                conn.execute(
                    text("""
                        UPDATE pedido
                        SET total_final = COALESCE((
                            SELECT ROUND(SUM(qty_final * preco_unitario) * 1.10, 2)
                            FROM pedido_item WHERE pedido_id = :pid
                        ), 0)
                        WHERE id = :pid
                    """),
                    {"pid": pedido_id},
                )

            conn.commit()
            print(f"💾 [DB] Pedido id={pedido_id} atualizado (status={status}).")
            return obter_pedido(pedido_id)
        except Exception as e:
            conn.rollback()
            print(f"❌ [DB SQL ERROR] atualizar_pedido_garcom: {e}")
            return None


def estatisticas_admin() -> dict:
    """Estatísticas para o painel admin."""
    if not _DB_ENABLED or not _ENGINE:
        return {
            "consultas_hoje": 0,
            "feedbacks_total": 0,
            "pedidos_total": 0,
            "reclamacoes": 0,
            "pedidos_pendentes": 0,
            "pedidos_confirmados": 0,
            "pedidos_cancelados": 0,
        }
    try:
        with _ENGINE.connect() as conn:
            consultas_hoje = conn.execute(text("""
                SELECT COUNT(*) FROM mensagem_chat
                WHERE role = 'user' AND created_at::date = CURRENT_DATE
            """)).scalar() or 0

            fb = conn.execute(text("""
                SELECT
                    COUNT(*) AS total,
                    COUNT(*) FILTER (WHERE tipo = 'reclamacao') AS reclamacoes
                FROM feedback
            """)).fetchone()

            pd = conn.execute(text("""
                SELECT
                    COUNT(*) AS total,
                    COUNT(*) FILTER (WHERE status = 'pendente') AS pend,
                    COUNT(*) FILTER (WHERE status = 'confirmado') AS conf,
                    COUNT(*) FILTER (WHERE status = 'cancelado') AS canc
                FROM pedido
            """)).fetchone()

            return {
                "consultas_hoje": int(consultas_hoje),
                "feedbacks_total": int(fb[0] or 0),
                "reclamacoes": int(fb[1] or 0),
                "pedidos_total": int(pd[0] or 0),
                "pedidos_pendentes": int(pd[1] or 0),
                "pedidos_confirmados": int(pd[2] or 0),
                "pedidos_cancelados": int(pd[3] or 0),
            }
    except Exception as e:
        print(f"❌ [DB SQL ERROR] estatisticas_admin: {e}")
        return {
            "consultas_hoje": 0, "feedbacks_total": 0, "pedidos_total": 0,
            "reclamacoes": 0, "pedidos_pendentes": 0,
            "pedidos_confirmados": 0, "pedidos_cancelados": 0,
        }


def listar_consultas_recentes(limit: int = 50) -> list:
    """Retorna mensagens recentes de usuários (consultas) para o painel admin."""
    if not _DB_ENABLED or not _ENGINE:
        return []
    try:
        with _ENGINE.connect() as conn:
            rows = conn.execute(
                text("""
                    SELECT m.id, m.conteudo, m.created_at, s.session_id
                    FROM mensagem_chat m
                    LEFT JOIN sessao_chat s ON s.id = m.sessao_id
                    WHERE m.role = 'user'
                    ORDER BY m.created_at DESC
                    LIMIT :lim
                """),
                {"lim": limit},
            ).fetchall()
            return [
                {
                    "id": r[0],
                    "conteudo": r[1],
                    "created_at": r[2].isoformat() if r[2] else None,
                    "session_id": r[3],
                }
                for r in rows
            ]
    except Exception as e:
        print(f"❌ [DB SQL ERROR] listar_consultas_recentes: {e}")
        return []


def _pedido_to_dict(row, items_rows) -> dict:
    """
    row: (id, numero, session_id, status, total_estimado, total_com_servico,
          total_final, garcom_nome, garcom_obs, created_at, updated_at)
    items_rows: lista de tuplas (id, nome, quantidade, qty_final, preco_unitario, observacao, posicao)
    """
    return {
        "id": row[0],
        "numero": int(row[1]),
        "number": f"{int(row[1]):03d}",
        "session_id": row[2],
        "status": row[3],
        "total_estimado": float(row[4] or 0),
        "total_com_servico": float(row[5] or 0),
        "total_final": float(row[6]) if row[6] is not None else None,
        "garcom_nome": row[7] or "",
        "garcom_obs": row[8] or "",
        "created_at": row[9].isoformat() if row[9] else None,
        "updated_at": row[10].isoformat() if row[10] else None,
        "items": [
            {
                "id": it[0],
                "nome": it[1],
                "quantidade": int(it[2]),
                "qty_final": int(it[3]),
                "preco_unitario": float(it[4] or 0),
                "observacao": it[5] or "",
                "posicao": int(it[6]),
            }
            for it in items_rows
        ],
    }
