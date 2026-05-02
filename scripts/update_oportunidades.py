"""
update_oportunidades.py — Pipeline Diário de Oportunidades PNCP

Consulta a API do PNCP para listar compras com proposta em aberto
e faz upsert na tabela `compras_abertas` do BigQuery.

Uso:
    python scripts/update_oportunidades.py
    python scripts/update_oportunidades.py --dias 7  (busca dos últimos 7 dias)
    python scripts/update_oportunidades.py --dry-run  (apenas exibe, não salva)

Sugestão de agendamento (crontab):
    0 3 * * * cd /app && python scripts/update_oportunidades.py >> /var/log/pncp_update.log 2>&1
"""

import os
import sys
import json
import time
import argparse
import logging
from datetime import datetime, timedelta, timezone

import requests
from google.cloud import bigquery

# ─── Configuração ─────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

GCP_PROJECT_ID = os.environ.get("GCP_PROJECT_ID", "pncp-466018")
GCP_DATASET_ID = os.environ.get("GCP_DATASET_ID", "pncp_data")
TABLE_ID = f"{GCP_PROJECT_ID}.{GCP_DATASET_ID}.compras_abertas"

PNCP_BASE_URL = "https://pncp.gov.br/api/consulta/v1"
REQUEST_DELAY = 2   # Segundos entre requisições para não sobrecarregar a API
PAGE_SIZE = 100        # Máximo suportado pela API PNCP


# ─── Criação da tabela se não existir ─────────────────────────────────────────
CREATE_TABLE_SQL = f"""
CREATE TABLE IF NOT EXISTS `{TABLE_ID}` (
    numeroControlePNCPCompra    STRING NOT NULL,
    anoCompra                   INT64,
    sequencialCompra            INT64,
    cnpjOrgao                   STRING,
    nomeOrgao                   STRING,
    nomeUnidadeOrgao            STRING,
    codigoUnidadeOrgao          STRING,
    uf                          STRING,
    ufNome                      STRING,
    municipio                   STRING,
    modalidadeId                INT64,
    modalidadeNome              STRING,
    objetoCompra                STRING,
    informacaoComplementar      STRING,
    valorTotalEstimado          FLOAT64,
    valorTotalHomologado        FLOAT64,
    dataPublicacaoPncp          TIMESTAMP,
    dataAberturaProposta        TIMESTAMP,
    dataEncerramentoProposta    TIMESTAMP,
    situacaoCompraId            INT64,
    situacaoCompraNome          STRING,
    linkSistemaOrigem           STRING,
    fonteDados                  STRING,
    updated_at                  TIMESTAMP
)
OPTIONS (
    description = "Compras abertas extraídas da API PNCP — atualização diária"
)
"""


# ─── Funções de API ────────────────────────────────────────────────────────────
def fetch_compras_abertas(data_final: str, pagina: int = 1) -> dict:
    """
    Consulta a API PNCP de compras com proposta em aberto.
    Endpoint: GET /contratacoes/proposta?dataFinal=&pagina=
    """
    url = f"{PNCP_BASE_URL}/contratacoes/proposta"
    params = {
        "dataFinal": data_final,
        "pagina": pagina,
        "tamanhoPagina": 50,
    }
    resp = requests.get(url, params=params)
    resp.raise_for_status()
    return resp.json()


def fetch_all_pages(data_final: str):
    """Busca todas as páginas de compras abertas para o período especificado."""
    all_items = []
    pagina = 1
    total_paginas = None

    while True:
        log.info(f"  Buscando página {pagina}" + (f"/{total_paginas}" if total_paginas else "") + "...")
        try:
            data = fetch_compras_abertas(data_final, pagina)
        except requests.HTTPError as e:
            if e.response.status_code == 404:
                log.info("  Sem mais resultados (404).")
                break
            raise

        # A API retorna paginado — campo "data" contém os itens
        items = data.get("data", []) if isinstance(data, dict) else data
        if not items:
            break

        all_items.extend(items)

        # Controle de paginação
        if isinstance(data, dict):
            total_paginas = data.get("totalPaginas") or data.get("totalPages")
            if total_paginas and pagina >= total_paginas:
                break

        pagina += 1
        time.sleep(REQUEST_DELAY)

    return all_items


# ─── Transformação ─────────────────────────────────────────────────────────────
def transform(raw: dict) -> dict:
    """Normaliza um item da API PNCP para o schema BigQuery."""
    def safe_float(val):
        try:
            return float(val) if val is not None else None
        except (ValueError, TypeError):
            return None

    def safe_int(val):
        try:
            return int(val) if val is not None else None
        except (ValueError, TypeError):
            return None

    def safe_ts(val):
        if not val:
            return None
        return val.replace("Z", "+00:00") if isinstance(val, str) else None

    orgao = raw.get("orgaoEntidade") or {}
    unidade = raw.get("unidadeOrgao") or {}

    return {
        # API retorna "numeroControlePNCP", não "numeroControlePNCPCompra"
        "numeroControlePNCPCompra": raw.get("numeroControlePNCP") or raw.get("numeroControlePNCPCompra") or "",
        "anoCompra": safe_int(raw.get("anoCompra")),
        "sequencialCompra": safe_int(raw.get("sequencialCompra")),
        "cnpjOrgao": str(orgao.get("cnpj") or raw.get("cnpjOrgao") or ""),
        "nomeOrgao": orgao.get("razaoSocial") or raw.get("nomeOrgao") or "",
        "nomeUnidadeOrgao": unidade.get("nomeUnidade") or raw.get("nomeUnidadeOrgao") or "",
        "codigoUnidadeOrgao": unidade.get("codigoUnidade") or raw.get("codigoUnidadeOrgao") or "",
        "uf": unidade.get("ufSigla") or raw.get("uf") or "",
        "ufNome": unidade.get("ufNome") or raw.get("ufNome") or "",
        "municipio": unidade.get("municipioNome") or raw.get("municipio") or "",
        "modalidadeId": safe_int(raw.get("modalidadeId")),
        "modalidadeNome": raw.get("modalidadeNome") or "",
        "objetoCompra": raw.get("objetoCompra") or "",
        "informacaoComplementar": raw.get("informacaoComplementar") or "",
        "valorTotalEstimado": safe_float(raw.get("valorTotalEstimado")),
        "valorTotalHomologado": safe_float(raw.get("valorTotalHomologado")),
        "dataPublicacaoPncp": safe_ts(raw.get("dataPublicacaoPncp")),
        "dataAberturaProposta": safe_ts(raw.get("dataAberturaProposta")),
        "dataEncerramentoProposta": safe_ts(raw.get("dataEncerramentoProposta")),
        "situacaoCompraId": safe_int(raw.get("situacaoCompraId")),
        "situacaoCompraNome": raw.get("situacaoCompraNome") or "",
        "linkSistemaOrigem": raw.get("linkSistemaOrigem") or "",
        "fonteDados": "PNCP_API",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


# ─── BigQuery: Upsert ──────────────────────────────────────────────────────────
def upsert_to_bigquery(rows: list, client: bigquery.Client, dry_run: bool = False) -> tuple[int, int]:
    if dry_run or not rows:
        return len(rows), 0

    temp_table = f"{GCP_PROJECT_ID}.{GCP_DATASET_ID}.compras_abertas_tmp"

    # Schema explícito — sem autodetect
    schema = [
        bigquery.SchemaField("numeroControlePNCPCompra",  "STRING"),
        bigquery.SchemaField("anoCompra",                 "INTEGER"),
        bigquery.SchemaField("sequencialCompra",          "INTEGER"),
        bigquery.SchemaField("cnpjOrgao",                 "STRING"),
        bigquery.SchemaField("nomeOrgao",                 "STRING"),
        bigquery.SchemaField("nomeUnidadeOrgao",          "STRING"),
        bigquery.SchemaField("codigoUnidadeOrgao",        "STRING"),
        bigquery.SchemaField("uf",                        "STRING"),
        bigquery.SchemaField("ufNome",                    "STRING"),
        bigquery.SchemaField("municipio",                 "STRING"),
        bigquery.SchemaField("modalidadeId",              "INTEGER"),
        bigquery.SchemaField("modalidadeNome",            "STRING"),
        bigquery.SchemaField("objetoCompra",              "STRING"),
        bigquery.SchemaField("informacaoComplementar",    "STRING"),
        bigquery.SchemaField("valorTotalEstimado",        "FLOAT"),
        bigquery.SchemaField("valorTotalHomologado",      "FLOAT"),
        bigquery.SchemaField("dataPublicacaoPncp",        "TIMESTAMP"),
        bigquery.SchemaField("dataAberturaProposta",      "TIMESTAMP"),
        bigquery.SchemaField("dataEncerramentoProposta",  "TIMESTAMP"),
        bigquery.SchemaField("situacaoCompraId",          "INTEGER"),
        bigquery.SchemaField("situacaoCompraNome",        "STRING"),
        bigquery.SchemaField("linkSistemaOrigem",         "STRING"),
        bigquery.SchemaField("fonteDados",                "STRING"),
        bigquery.SchemaField("updated_at",                "TIMESTAMP"),
    ]

    job_config = bigquery.LoadJobConfig(
        write_disposition="WRITE_TRUNCATE",
        source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
        schema=schema,  # schema explícito
    )
    load_job = client.load_table_from_json(rows, temp_table, job_config=job_config)
    load_job.result()

    rebuild_sql = f"""
    CREATE OR REPLACE TABLE `{TABLE_ID}` AS
    SELECT * EXCEPT(rn)
    FROM (
        SELECT *,
               ROW_NUMBER() OVER (
                   PARTITION BY numeroControlePNCPCompra
                   ORDER BY updated_at DESC
               ) AS rn
        FROM (
            SELECT * FROM `{TABLE_ID}`
            UNION ALL
            SELECT * FROM `{temp_table}`
        )
    )
    WHERE rn = 1
    """
    client.query(rebuild_sql).result()
    client.delete_table(temp_table, not_found_ok=True)

    return len(rows), 0


def old3_upsert_to_bigquery(rows: list, client: bigquery.Client, dry_run: bool = False) -> tuple[int, int]:
    if dry_run or not rows:
        return len(rows), 0

    temp_table = f"{GCP_PROJECT_ID}.{GCP_DATASET_ID}.compras_abertas_tmp"

    # Schema explícito — sem autodetect
    schema = [
        bigquery.SchemaField("numeroControlePNCPCompra",  "STRING"),
        bigquery.SchemaField("anoCompra",                 "INTEGER"),
        bigquery.SchemaField("sequencialCompra",          "INTEGER"),
        bigquery.SchemaField("cnpjOrgao",                 "STRING"),
        bigquery.SchemaField("nomeOrgao",                 "STRING"),
        bigquery.SchemaField("nomeUnidadeOrgao",          "STRING"),
        bigquery.SchemaField("codigoUnidadeOrgao",        "STRING"),
        bigquery.SchemaField("uf",                        "STRING"),
        bigquery.SchemaField("ufNome",                    "STRING"),
        bigquery.SchemaField("municipio",                 "STRING"),
        bigquery.SchemaField("modalidadeId",              "INTEGER"),
        bigquery.SchemaField("modalidadeNome",            "STRING"),
        bigquery.SchemaField("objetoCompra",              "STRING"),
        bigquery.SchemaField("informacaoComplementar",    "STRING"),
        bigquery.SchemaField("valorTotalEstimado",        "FLOAT"),
        bigquery.SchemaField("valorTotalHomologado",      "FLOAT"),
        bigquery.SchemaField("dataPublicacaoPncp",        "TIMESTAMP"),
        bigquery.SchemaField("dataAberturaProposta",      "TIMESTAMP"),
        bigquery.SchemaField("dataEncerramentoProposta",  "TIMESTAMP"),
        bigquery.SchemaField("situacaoCompraId",          "INTEGER"),
        bigquery.SchemaField("situacaoCompraNome",        "STRING"),
        bigquery.SchemaField("linkSistemaOrigem",         "STRING"),
        bigquery.SchemaField("fonteDados",                "STRING"),
        bigquery.SchemaField("updated_at",                "TIMESTAMP"),
    ]

    job_config = bigquery.LoadJobConfig(
        write_disposition="WRITE_TRUNCATE",
        source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
        schema=schema,  # schema explícito
    )
    load_job = client.load_table_from_json(rows, temp_table, job_config=job_config)
    load_job.result()

    merge_sql = f"""
        MERGE `{TABLE_ID}` T
        USING `{temp_table}` S
        ON T.numeroControlePNCPCompra = S.numeroControlePNCPCompra
        WHEN MATCHED THEN UPDATE SET
            T.situacaoCompraId         = S.situacaoCompraId,
            T.situacaoCompraNome       = S.situacaoCompraNome,
            T.valorTotalEstimado       = S.valorTotalEstimado,
            T.valorTotalHomologado     = S.valorTotalHomologado,
            T.dataEncerramentoProposta = S.dataEncerramentoProposta,
            T.updated_at               = S.updated_at
        WHEN NOT MATCHED THEN INSERT ROW
    """
    client.query(merge_sql).result()
    client.delete_table(temp_table, not_found_ok=True)

    return len(rows), 0


def old2_upsert_to_bigquery(rows: list, client: bigquery.Client, dry_run: bool = False) -> tuple[int, int]:
    if dry_run or not rows:
        return len(rows), 0

    temp_table = f"{GCP_PROJECT_ID}.{GCP_DATASET_ID}.compras_abertas_tmp"

    # 1. Carrega na tabela temporária via load job (sem streaming buffer)
    job_config = bigquery.LoadJobConfig(
        write_disposition="WRITE_TRUNCATE",
        source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
        autodetect=True,
    )
    load_job = client.load_table_from_json(rows, temp_table, job_config=job_config)
    load_job.result()

    # 2. MERGE da temp na tabela principal
    merge_sql = f"""
        MERGE `{TABLE_ID}` T
        USING `{temp_table}` S
        ON T.numeroControlePNCPCompra = S.numeroControlePNCPCompra
        WHEN MATCHED THEN UPDATE SET
            T.situacaoCompraId          = S.situacaoCompraId,
            T.situacaoCompraNome        = S.situacaoCompraNome,
            T.valorTotalEstimado        = S.valorTotalEstimado,
            T.valorTotalHomologado      = S.valorTotalHomologado,
            T.dataEncerramentoProposta  = S.dataEncerramentoProposta,
            T.updated_at                = S.updated_at
        WHEN NOT MATCHED THEN INSERT ROW
    """
    client.query(merge_sql).result()

    # 3. Limpa a tabela temporária
    client.delete_table(temp_table, not_found_ok=True)

    return len(rows), 0
def old_upsert_to_bigquery(rows: list, client: bigquery.Client, dry_run: bool = False) -> tuple[int, int]:
    """
    Faz upsert das linhas na tabela compras_abertas do BigQuery.
    BigQuery não tem UPSERT nativo, então: DELETE + INSERT em lote.
    Retorna (inseridos, erros).
    """
    if dry_run or not rows:
        return len(rows), 0

    # Filtrar IDs para delete
    ids = [r["numeroControlePNCPCompra"] for r in rows if r.get("numeroControlePNCPCompra")]

    if ids:
        # DELETE existing records para os IDs que vamos reprocessar
        ids_str = ", ".join(f"'{i}'" for i in ids)
        delete_sql = f"""
            DELETE FROM `{TABLE_ID}`
            WHERE numeroControlePNCPCompra IN ({ids_str})
        """
        client.query(delete_sql).result()

    # INSERT em lote
    errors = client.insert_rows_json(TABLE_ID, rows)
    error_count = len(errors)
    if errors:
        log.warning(f"  {error_count} erros no insert: {errors[:3]}")

    return len(rows) - error_count, error_count


def ensure_table_exists(client: bigquery.Client):
    """Cria a tabela se não existir."""
    try:
        client.query(CREATE_TABLE_SQL).result()
        log.info("Tabela compras_abertas verificada/criada.")
    except Exception as e:
        log.error(f"Erro ao criar tabela: {e}")
        raise


# ─── Main ──────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Pipeline de Oportunidades PNCP")
    parser.add_argument("--dias", type=int, default=1,
                        help="Quantos dias retroativos buscar (padrão: 1 = hoje)")
    parser.add_argument("--data-inicial", type=str, default=None,
                        help="Data inicial no formato YYYYMMDD (sobrepõe --dias)")
    parser.add_argument("--data-final", type=str, default=None,
                        help="Data final no formato YYYYMMDD (padrão: hoje)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Apenas exibe os dados, não salva no BigQuery")
    args = parser.parse_args()

    hoje = datetime.now(timezone.utc)
    data_final_dt = datetime.strptime(args.data_final, "%Y%m%d") if args.data_final else hoje
    data_inicial_dt = datetime.strptime(args.data_inicial, "%Y%m%d") if args.data_inicial else (data_final_dt - timedelta(days=args.dias - 1))

    data_inicial = data_inicial_dt.strftime("%Y%m%d")
    data_final = data_final_dt.strftime("%Y%m%d")

    log.info(f"{'[DRY RUN] ' if args.dry_run else ''}Iniciando extração PNCP: {data_inicial} → {data_final}")

    # BigQuery client
    bq = bigquery.Client(project=GCP_PROJECT_ID)
    ensure_table_exists(bq)

    # Fetch
    log.info("Buscando compras abertas na API PNCP...")
    raw_items = fetch_all_pages(data_final)
    log.info(f"  Total bruto recebido: {len(raw_items)} registros")

    if not raw_items:
        log.info("Nenhum registro novo encontrado. Encerrando.")
        return

    # Transform
    rows = [transform(r) for r in raw_items]
    rows = [r for r in rows if r["numeroControlePNCPCompra"]]  # Filtrar inválidos
    log.info(f"  Registros válidos após transformação: {len(rows)}")

    if args.dry_run:
        log.info("[DRY RUN] Exemplos dos primeiros 3 registros:")
        for r in rows[:3]:
            log.info(json.dumps(r, ensure_ascii=False, indent=2))
        log.info("[DRY RUN] Nenhum dado foi salvo.")
        return

    # Upsert
    log.info(f"Fazendo upsert de {len(rows)} registros no BigQuery...")
    inseridos, erros = upsert_to_bigquery(rows, bq)
    log.info(f"✅ Concluído: {inseridos} inseridos, {erros} erros.")


if __name__ == "__main__":
    main()