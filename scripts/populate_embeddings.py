"""
populate_embeddings.py
======================
Popula a coluna `embedding` nas tabelas do BigQuery usando Gemini text-embedding-004.

Tabelas cobertas:
  - itens           → incremental (somente WHERE embedding IS NULL), prioriza 2026
  - compras_abertas → completo (58k linhas, rápido)
  - compras_futuras → completo (29k linhas, rápido)

Características:
  - Checkpoint JSON por tabela para retomada segura após interrupção
  - Lotes de BATCH_SIZE registros por consulta BigQuery
  - Retry automático (3 tentativas) em caso de erros da API Gemini
  - Rate limiting: pausa entre lotes para evitar quota exceeded
  - Progresso exibido em tempo real

Uso:
    python scripts/populate_embeddings.py                   # Todas as tabelas
    python scripts/populate_embeddings.py --table itens     # Somente itens
    python scripts/populate_embeddings.py --dry-run         # Testa com 20 linhas

Requisitos no ambiente:
    GEMINI_API_KEY, GCP_PROJECT_ID, GCP_DATASET_ID, GOOGLE_CREDENTIALS_JSON
"""

import os
import sys
import json
import time
import base64
import argparse
import traceback
from datetime import datetime

# ── Adiciona a raiz do projeto ao path ──────────────────────────────────────
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# ── Carregar .env ────────────────────────────────────────────────────────────
env_path = os.path.join(ROOT, '.env')
if os.path.exists(env_path):
    with open(env_path, 'r') as f:
        for line in f:
            line = line.strip()
            if line and '=' in line and not line.startswith('#'):
                k, v = line.split('=', 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    print(f"✅ Variáveis carregadas de {env_path}")

from google.cloud import bigquery as bq_module
from google import genai
from google.genai import types as genai_types

# ── Configuração ─────────────────────────────────────────────────────────────
BATCH_SIZE     = 200     # Registros por lote de consulta BigQuery
EMBED_BATCH    = 50      # Registros por chamada à API do Gemini (máx. recomendado)
SLEEP_BETWEEN  = 1.0     # Segundos entre lotes Gemini (rate limiting)
MAX_RETRIES    = 3       # Tentativas em caso de erro de API
EMBEDDING_MODEL = "gemini-embedding-001"  # 3072 dims, modelo estável da API Gemini
EMBEDDING_DIMS  = 3072

CHECKPOINT_DIR = os.path.join(ROOT, 'scripts')

# ── Definição das tabelas e suas colunas ─────────────────────────────────────
TABLE_CONFIGS = {
    "itens": {
        "id_col":   "id",
        "text_col": "descricao",
        "incremental": True,   # somente onde embedding IS NULL
    },
    "compras_abertas": {
        "id_col":   "numeroControlePNCPCompra",
        "text_col": "objetoCompra",
        "incremental": True,
    },
    "compras_futuras": {
        "id_col":   "numeroControlePNCP",
        "text_col": "objetoCompra",
        "incremental": True,
    },
}


# ── Credenciais ──────────────────────────────────────────────────────────────
def _get_bq_client(project_id: str) -> bq_module.Client:
    creds_b64 = os.environ.get('GOOGLE_CREDENTIALS_JSON', '')
    if creds_b64:
        try:
            creds_json = json.loads(base64.b64decode(creds_b64).decode('utf-8'))
            if creds_json.get('type') == 'authorized_user':
                from google.oauth2.credentials import Credentials
                creds = Credentials(
                    token=None,
                    refresh_token=creds_json['refresh_token'],
                    client_id=creds_json['client_id'],
                    client_secret=creds_json['client_secret'],
                    token_uri='https://oauth2.googleapis.com/token'
                )
            else:
                from google.oauth2 import service_account
                creds = service_account.Credentials.from_service_account_info(creds_json)
            return bq_module.Client(project=project_id, credentials=creds)
        except Exception as e:
            print(f"⚠️  Falha ao carregar credenciais: {e}. Tentando ADC...")
    return bq_module.Client(project=project_id)


def _get_gemini_client() -> genai.Client:
    api_key = os.environ.get('GEMINI_API_KEY')
    if not api_key:
        raise ValueError("❌ GEMINI_API_KEY não configurada no ambiente.")
    return genai.Client(api_key=api_key)


# ── Checkpoint ───────────────────────────────────────────────────────────────
def checkpoint_path(table: str) -> str:
    return os.path.join(CHECKPOINT_DIR, f'.embedding_checkpoint_{table}.json')

def load_checkpoint(table: str) -> dict:
    path = checkpoint_path(table)
    if os.path.exists(path):
        with open(path, 'r') as f:
            return json.load(f)
    return {"offset": 0, "processed": 0, "errors": 0, "started_at": datetime.now().isoformat()}

def save_checkpoint(table: str, data: dict):
    data["updated_at"] = datetime.now().isoformat()
    with open(checkpoint_path(table), 'w') as f:
        json.dump(data, f, indent=2)

def delete_checkpoint(table: str):
    path = checkpoint_path(table)
    if os.path.exists(path):
        os.remove(path)


# ── Geração de Embeddings ────────────────────────────────────────────────────
def generate_embeddings_batch(texts: list[str], gemini_client: genai.Client) -> list[list[float]]:
    """Gera embeddings para uma lista de textos. Retorna lista de vetores."""
    texts_clean = [
        (t.strip().replace("\n", " ")[:2000] if t else "item sem descrição")
        for t in texts
    ]
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            result = gemini_client.models.embed_content(
                model=EMBEDDING_MODEL,
                contents=texts_clean,
                config=genai_types.EmbedContentConfig(task_type="RETRIEVAL_DOCUMENT"),
            )
            return [emb.values for emb in result.embeddings]
        except Exception as e:
            print(f"  ⚠️  Tentativa {attempt}/{MAX_RETRIES} falhou: {e}")
            if attempt < MAX_RETRIES:
                time.sleep(2 ** attempt)  # backoff exponencial
            else:
                raise


# ── Update BigQuery ──────────────────────────────────────────────────────────
def update_embeddings_batch(
    bq_client: bq_module.Client,
    pid: str, did: str,
    table: str,
    id_col: str,
    rows: list[dict],
    embeddings: list[list[float]],
) -> int:
    """
    Atualiza a coluna embedding via INSERT INTO uma tabela temporária de staging
    e depois faz MERGE. Mais eficiente do que múltiplos UPDATEs individuais.
    """
    staging_table = f"{pid}.{did}._emb_staging_{table}"

    # Schema da staging: apenas id + embedding
    staging_schema = [
        bq_module.SchemaField("row_id", "STRING", mode="REQUIRED"),
        bq_module.SchemaField("embedding", "FLOAT64", mode="REPEATED"),
    ]

    # Deletar staging se existir
    bq_client.delete_table(staging_table, not_found_ok=True)

    # Criar staging
    staging = bq_module.Table(staging_table, schema=staging_schema)
    bq_client.create_table(staging)

    # Inserir dados na staging
    to_insert = [
        {"row_id": str(row[id_col]), "embedding": emb}
        for row, emb in zip(rows, embeddings)
    ]
    errors = bq_client.insert_rows_json(staging_table, to_insert)
    if errors:
        print(f"  ⚠️  Erros ao inserir na staging: {errors[:3]}")

    # MERGE principal → staging
    id_type = "STRING" if id_col != "id" else "INT64"
    merge_sql = f"""
        MERGE `{pid}.{did}.{table}` AS target
        USING (
            SELECT SAFE_CAST(row_id AS {id_type}) AS row_id, embedding
            FROM `{staging_table}`
        ) AS src
        ON SAFE_CAST(target.{id_col} AS {id_type}) = src.row_id
        WHEN MATCHED THEN
            UPDATE SET target.embedding = src.embedding
    """
    job = bq_client.query(merge_sql)
    job.result()

    # Limpar staging
    bq_client.delete_table(staging_table, not_found_ok=True)

    return len(rows)


# ── Pipeline Principal ───────────────────────────────────────────────────────
def process_table(
    table: str,
    config: dict,
    bq: bq_module.Client,
    gemini: genai.Client,
    pid: str,
    did: str,
    dry_run: bool = False,
    limit_rows: int = None,
):
    id_col   = config["id_col"]
    text_col = config["text_col"]
    incremental = config.get("incremental", True)

    checkpoint = load_checkpoint(table)
    offset = checkpoint["offset"]
    processed = checkpoint["processed"]
    errors_count = checkpoint["errors"]

    print(f"\n{'='*60}")
    print(f"Tabela: {table}")
    print(f"  Coluna ID: {id_col} | Coluna texto: {text_col}")
    print(f"  Incremental (somente NULL): {incremental}")
    print(f"  Checkpoint: offset={offset:,}, processados={processed:,}")
    if dry_run:
        print(f"  ⚠️  DRY-RUN: apenas 20 linhas serão processadas")
    print(f"{'='*60}")

    total_rows_sql = f"""
        SELECT COUNT(*) as total
        FROM `{pid}.{did}.{table}`
        {"WHERE ARRAY_LENGTH(embedding) = 0 OR embedding IS NULL" if incremental else ""}
    """
    total = next(bq.query(total_rows_sql).result())['total']
    print(f"  Registros a processar: {total:,}")

    if total == 0:
        print("  ✅ Nenhum registro pendente. Pulando.")
        return

    effective_batch = 20 if dry_run else BATCH_SIZE
    max_iterations  = 1 if dry_run else (limit_rows // effective_batch + 1 if limit_rows else None)
    iteration = 0

    while True:
        if max_iterations and iteration >= max_iterations:
            break

        # Buscar lote do BigQuery
        where_clause = "WHERE ARRAY_LENGTH(embedding) = 0 OR embedding IS NULL" if incremental else ""
        sql = f"""
            SELECT {id_col}, {text_col}
            FROM `{pid}.{did}.{table}`
            {where_clause}
            LIMIT {effective_batch} OFFSET {offset}
        """
        try:
            rows = [dict(r) for r in bq.query(sql).result()]
        except Exception as e:
            print(f"  ❌ Erro ao buscar lote (offset={offset}): {e}")
            break

        if not rows:
            print(f"  ✅ Todos os registros processados! ({processed:,} total)")
            delete_checkpoint(table)
            break

        texts  = [r.get(text_col) or "" for r in rows]
        ids    = [r.get(id_col)   for r in rows]

        # Gerar embeddings em sub-lotes
        all_embeddings = []
        for i in range(0, len(texts), EMBED_BATCH):
            sub_texts = texts[i:i+EMBED_BATCH]
            try:
                sub_embs = generate_embeddings_batch(sub_texts, gemini)
                all_embeddings.extend(sub_embs)
            except Exception as e:
                print(f"  ❌ Erro na API Gemini (sub-lote {i}): {e}")
                errors_count += 1
                # Preenche com None para manter alinhamento
                all_embeddings.extend([None] * len(sub_texts))

        # Filtrar pares com embedding válido
        valid_rows = [(r, e) for r, e in zip(rows, all_embeddings) if e is not None]
        if not valid_rows:
            print(f"  ⚠️  Lote offset={offset}: todos os embeddings falharam. Avançando.")
            offset += len(rows)
            save_checkpoint(table, {"offset": offset, "processed": processed, "errors": errors_count})
            continue

        valid_row_dicts, valid_embeddings = zip(*valid_rows)

        # Salvar no BigQuery
        try:
            count = update_embeddings_batch(bq, pid, did, table, id_col, list(valid_row_dicts), list(valid_embeddings))
            processed += count
        except Exception as e:
            print(f"  ❌ Erro ao salvar batch (offset={offset}): {e}")
            traceback.print_exc()
            errors_count += 1

        offset += len(rows)
        iteration += 1

        pct = (offset / total * 100) if total > 0 else 0
        print(f"  [{datetime.now().strftime('%H:%M:%S')}] Offset {offset:>8,} | {pct:5.1f}% | Processados: {processed:,} | Erros: {errors_count}")

        save_checkpoint(table, {"offset": offset, "processed": processed, "errors": errors_count, "started_at": checkpoint.get("started_at", "")})

        time.sleep(SLEEP_BETWEEN)


# ── Criação de Vector Index ──────────────────────────────────────────────────
def create_vector_index(bq: bq_module.Client, pid: str, did: str, table: str):
    """Cria o Vector Index para VECTOR_SEARCH no BigQuery."""
    index_name = f"idx_{table}_embedding"
    sql = f"""
        CREATE VECTOR INDEX IF NOT EXISTS `{index_name}`
        ON `{pid}.{did}.{table}`(embedding)
        OPTIONS(distance_type='COSINE', index_type='IVF')
    """
    print(f"\nCriando Vector Index em {table}...")
    try:
        bq.query(sql).result()
        print(f"  ✅ Vector Index '{index_name}' criado em {table}")
    except Exception as e:
        # O índice é criado assincronamente pelo BigQuery em background
        if "already exists" in str(e).lower():
            print(f"  ℹ️  Índice já existe em {table}")
        else:
            print(f"  ⚠️  Criação do índice iniciada (executa em background): {e}")


# ── Entry Point ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Popula embeddings no BigQuery via Gemini")
    parser.add_argument("--table", choices=list(TABLE_CONFIGS.keys()), help="Processar apenas esta tabela")
    parser.add_argument("--dry-run", action="store_true", help="Testar com 20 linhas apenas")
    parser.add_argument("--skip-index", action="store_true", help="Pular criação do Vector Index")
    args = parser.parse_args()

    pid = os.environ.get('GCP_PROJECT_ID', 'pncp-466018')
    did = os.environ.get('GCP_DATASET_ID', 'pncp_data')

    print(f"\n🚀 populate_embeddings.py")
    print(f"   Project: {pid} | Dataset: {did}")
    print(f"   Modelo: {EMBEDDING_MODEL} ({EMBEDDING_DIMS} dims)")
    print(f"   Batch BQ: {BATCH_SIZE} | Batch Gemini: {EMBED_BATCH}")

    bq = _get_bq_client(pid)
    gemini = _get_gemini_client()

    tables_to_process = {args.table: TABLE_CONFIGS[args.table]} if args.table else TABLE_CONFIGS

    for table_name, config in tables_to_process.items():
        process_table(
            table=table_name,
            config=config,
            bq=bq,
            gemini=gemini,
            pid=pid,
            did=did,
            dry_run=args.dry_run,
        )

    if not args.skip_index:
        print(f"\n{'='*60}")
        print("Criando Vector Indexes...")
        for table_name in tables_to_process:
            create_vector_index(bq, pid, did, table_name)

    print(f"\n✅ Pipeline concluído!")
