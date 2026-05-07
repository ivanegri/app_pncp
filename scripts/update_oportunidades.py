"""
update_oportunidades.py — Pipeline Diário de Oportunidades PNCP

Consulta a API do PNCP para listar compras com proposta em aberto
e faz upsert incremental na tabela `compras_abertas` e `compras_abertas_itens` do BigQuery.

Funcionalidades:
  - Busca de itens: baixa os itens de cada edital para possibilitar pesquisa detalhada
  - Checkpoint automático: retoma do ponto de parada em caso de interrupção
  - Upsert por lote: salva no BigQuery a cada página (não perde dados)
  - Retry com backoff: 3 tentativas por página/item com espera exponencial
  - Credenciais via GOOGLE_CREDENTIALS_JSON (mesmo padrão do app Flask)
"""

import os
import sys
import json
import time
import argparse
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
import concurrent.futures

import requests
from google.cloud import bigquery
from google.oauth2 import service_account

# ─── Configuração ──────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

GCP_PROJECT_ID  = os.environ.get("GCP_PROJECT_ID",  "pncp-466018")
GCP_DATASET_ID  = os.environ.get("GCP_DATASET_ID",  "pncp_data")
TABLE_ID        = f"{GCP_PROJECT_ID}.{GCP_DATASET_ID}.compras_abertas"
TABLE_ID_ITENS  = f"{GCP_PROJECT_ID}.{GCP_DATASET_ID}.compras_abertas_itens"

PNCP_BASE_URL   = "https://pncp.gov.br/api/consulta/v1"
PNCP_API_URL    = "https://pncp.gov.br/api/pncp/v1"
PAGE_SIZE       = 50    # Tamanho de página da API PNCP
REQUEST_DELAY   = 3     # Segundos entre requisições
MAX_RETRIES     = 3     # Tentativas por página
RETRY_BACKOFF   = 2     # Fator de backoff: 2s, 4s, 8s
MAX_WORKERS     = 10    # Workers para buscar itens concorrentemente

CHECKPOINT_DIR  = Path(__file__).parent  # mesma pasta do script


# ─── Credenciais BigQuery ──────────────────────────────────────────────────────
def get_bq_client() -> bigquery.Client:
    creds_json_str = os.environ.get("GOOGLE_CREDENTIALS_JSON", "")
    if creds_json_str and creds_json_str.strip():
        try:
            creds_info = json.loads(creds_json_str)
            credentials = service_account.Credentials.from_service_account_info(
                creds_info,
                scopes=["https://www.googleapis.com/auth/cloud-platform"],
            )
            return bigquery.Client(project=GCP_PROJECT_ID, credentials=credentials)
        except Exception as e:
            log.warning(f"Falha ao carregar GOOGLE_CREDENTIALS_JSON: {e}. Tentando ADC...")
    return bigquery.Client(project=GCP_PROJECT_ID)


# ─── Checkpoint ────────────────────────────────────────────────────────────────
def checkpoint_path(data_final: str) -> Path:
    return CHECKPOINT_DIR / f".pncp_checkpoint_{data_final}.json"

def load_checkpoint(data_final: str) -> dict:
    cp = checkpoint_path(data_final)
    if cp.exists():
        try:
            data = json.loads(cp.read_text())
            log.info(f"Checkpoint encontrado: retomando da pagina {data['proxima_pagina']} ({data['registros_salvos']} compras ja salvas)")
            return data
        except Exception as e:
            log.warning(f"Checkpoint invalido, ignorando: {e}")
    return {"proxima_pagina": 1, "total_paginas": None, "registros_salvos": 0, "itens_salvos": 0, "paginas_com_erro": []}

def save_checkpoint(data_final: str, proxima_pagina: int, total_paginas, registros_salvos: int, itens_salvos: int, paginas_com_erro: list):
    cp = checkpoint_path(data_final)
    data = {
        "proxima_pagina":   proxima_pagina,
        "total_paginas":    total_paginas,
        "registros_salvos": registros_salvos,
        "itens_salvos":     itens_salvos,
        "paginas_com_erro": paginas_com_erro,
        "atualizado_em":    datetime.now(timezone.utc).isoformat(),
    }
    cp.write_text(json.dumps(data, ensure_ascii=False, indent=2))

def clear_checkpoint(data_final: str):
    cp = checkpoint_path(data_final)
    if cp.exists():
        cp.unlink()
        log.info("Checkpoint removido (execucao completa).")


# ─── Criação da tabela ─────────────────────────────────────────────────────────
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
) OPTIONS (description = "Compras abertas extraidas da API PNCP - atualizacao diaria")
"""

CREATE_TABLE_SQL_ITENS = f"""
CREATE TABLE IF NOT EXISTS `{TABLE_ID_ITENS}` (
    numeroControlePNCPCompra    STRING NOT NULL,
    numeroItem                  INT64 NOT NULL,
    descricao                   STRING,
    quantidade                  FLOAT64,
    valorUnitarioEstimado       FLOAT64,
    valorTotal                  FLOAT64,
    unidadeMedida               STRING,
    situacaoItem                STRING,
    updated_at                  TIMESTAMP
) OPTIONS (description = "Itens das compras abertas extraidas da API PNCP")
"""

BQ_SCHEMA = [
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

BQ_SCHEMA_ITENS = [
    bigquery.SchemaField("numeroControlePNCPCompra",  "STRING"),
    bigquery.SchemaField("numeroItem",                "INTEGER"),
    bigquery.SchemaField("descricao",                 "STRING"),
    bigquery.SchemaField("quantidade",                "FLOAT"),
    bigquery.SchemaField("valorUnitarioEstimado",     "FLOAT"),
    bigquery.SchemaField("valorTotal",                "FLOAT"),
    bigquery.SchemaField("unidadeMedida",             "STRING"),
    bigquery.SchemaField("situacaoItem",              "STRING"),
    bigquery.SchemaField("updated_at",                "TIMESTAMP"),
]

def ensure_tables_exist(client: bigquery.Client):
    try:
        client.query(CREATE_TABLE_SQL).result()
        client.query(CREATE_TABLE_SQL_ITENS).result()
        log.info("Tabelas compras_abertas e compras_abertas_itens verificadas/criadas.")
    except Exception as e:
        log.error(f"Erro ao criar tabelas: {e}")
        raise


# ─── Funções de API ────────────────────────────────────────────────────────────
def fetch_pagina(data_final: str, pagina: int, timeout: int = 60) -> dict:
    url = f"{PNCP_BASE_URL}/contratacoes/proposta"
    params = {"dataFinal": data_final, "pagina": pagina, "tamanhoPagina": PAGE_SIZE}
    resp = requests.get(url, params=params, timeout=timeout)
    resp.raise_for_status()
    return resp.json()

def fetch_pagina_com_retry(data_final: str, pagina: int):
    for tentativa in range(1, MAX_RETRIES + 1):
        try:
            return fetch_pagina(data_final, pagina)
        except requests.HTTPError as e:
            if e.response.status_code == 404:
                return None
            wait = RETRY_BACKOFF ** tentativa
            time.sleep(wait)
        except (requests.ConnectionError, requests.Timeout) as e:
            wait = RETRY_BACKOFF ** tentativa
            time.sleep(wait)
        except Exception as e:
            break
    log.error(f"  Pagina {pagina}: falhou apos {MAX_RETRIES} tentativas. Sera pulada.")
    return None

def fetch_itens(cnpj: str, ano: str, seq: str, timeout: int = 15) -> list:
    url = f"{PNCP_API_URL}/orgaos/{cnpj}/compras/{ano}/{seq}/itens"
    resp = requests.get(url, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    return data if isinstance(data, list) else []

def fetch_itens_com_retry(cnpj: str, ano: str, seq: str):
    for tentativa in range(1, MAX_RETRIES + 1):
        try:
            return fetch_itens(cnpj, ano, seq)
        except requests.HTTPError as e:
            if e.response.status_code == 404:
                return []
            wait = RETRY_BACKOFF ** tentativa
            time.sleep(wait)
        except (requests.ConnectionError, requests.Timeout):
            wait = RETRY_BACKOFF ** tentativa
            time.sleep(wait)
        except Exception:
            break
    return []

def worker_fetch_itens(row: dict):
    """Busca itens para um edital específico e os retorna formatados"""
    if not row or not row.get("cnpjOrgao") or not row.get("anoCompra") or not row.get("sequencialCompra"):
        return []
    
    cnpj = str(row["cnpjOrgao"])[:14]
    ano = str(row["anoCompra"])
    seq = str(row["sequencialCompra"]).zfill(6)
    
    raw_items = fetch_itens_com_retry(cnpj, ano, seq)
    
    formatted_items = []
    for item in raw_items:
        transformed = transform_item(item, row["numeroControlePNCPCompra"])
        if transformed:
            formatted_items.append(transformed)
    return formatted_items


# ─── Transformação ─────────────────────────────────────────────────────────────
def safe_float(val):
    try: return float(val) if val is not None else None
    except (ValueError, TypeError): return None

def safe_int(val):
    try: return int(val) if val is not None else None
    except (ValueError, TypeError): return None

def safe_ts(val):
    if not val: return None
    return val.replace("Z", "+00:00") if isinstance(val, str) else None

def transform(raw: dict):
    orgao   = raw.get("orgaoEntidade") or {}
    unidade = raw.get("unidadeOrgao") or {}
    numero  = raw.get("numeroControlePNCP") or raw.get("numeroControlePNCPCompra") or ""

    if not numero:
        return None

    return {
        "numeroControlePNCPCompra": numero,
        "anoCompra":                safe_int(raw.get("anoCompra")),
        "sequencialCompra":         safe_int(raw.get("sequencialCompra")),
        "cnpjOrgao":                str(orgao.get("cnpj") or raw.get("cnpjOrgao") or ""),
        "nomeOrgao":                orgao.get("razaoSocial") or raw.get("nomeOrgao") or "",
        "nomeUnidadeOrgao":         unidade.get("nomeUnidade") or raw.get("nomeUnidadeOrgao") or "",
        "codigoUnidadeOrgao":       unidade.get("codigoUnidade") or raw.get("codigoUnidadeOrgao") or "",
        "uf":                       unidade.get("ufSigla") or raw.get("uf") or "",
        "ufNome":                   unidade.get("ufNome") or raw.get("ufNome") or "",
        "municipio":                unidade.get("municipioNome") or raw.get("municipio") or "",
        "modalidadeId":             safe_int(raw.get("modalidadeId")),
        "modalidadeNome":           raw.get("modalidadeNome") or "",
        "objetoCompra":             raw.get("objetoCompra") or "",
        "informacaoComplementar":   raw.get("informacaoComplementar") or "",
        "valorTotalEstimado":       safe_float(raw.get("valorTotalEstimado")),
        "valorTotalHomologado":     safe_float(raw.get("valorTotalHomologado")),
        "dataPublicacaoPncp":       safe_ts(raw.get("dataPublicacaoPncp")),
        "dataAberturaProposta":     safe_ts(raw.get("dataAberturaProposta")),
        "dataEncerramentoProposta": safe_ts(raw.get("dataEncerramentoProposta")),
        "situacaoCompraId":         safe_int(raw.get("situacaoCompraId")),
        "situacaoCompraNome":       raw.get("situacaoCompraNome") or "",
        "linkSistemaOrigem":        raw.get("linkSistemaOrigem") or "",
        "fonteDados":               "PNCP_API",
        "updated_at":               datetime.now(timezone.utc).isoformat(),
    }

def transform_item(raw: dict, numero_controle: str):
    numero_item = safe_int(raw.get("numeroItem"))
    if not numero_item or not numero_controle:
        return None
    return {
        "numeroControlePNCPCompra": numero_controle,
        "numeroItem":               numero_item,
        "descricao":                raw.get("descricao") or "",
        "quantidade":               safe_float(raw.get("quantidade")),
        "valorUnitarioEstimado":    safe_float(raw.get("valorUnitarioEstimado")),
        "valorTotal":               safe_float(raw.get("valorTotal")),
        "unidadeMedida":            raw.get("unidadeMedida") or "",
        "situacaoItem":             raw.get("situacaoItemNome") or "",
        "updated_at":               datetime.now(timezone.utc).isoformat(),
    }


# ─── BigQuery: Upsert por lote ─────────────────────────────────────────────────
def upsert_lote(rows: list, client: bigquery.Client, table_id: str, schema: list, merge_on: list, merge_updates: list, dry_run: bool = False) -> int:
    if not rows:
        return 0
    if dry_run:
        return len(rows)

    temp_table = f"{GCP_PROJECT_ID}.{GCP_DATASET_ID}.temp_" + table_id.split(".")[-1]

    job_config = bigquery.LoadJobConfig(
        write_disposition="WRITE_TRUNCATE",
        source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
        schema=schema,
    )
    load_job = client.load_table_from_json(rows, temp_table, job_config=job_config)
    load_job.result()

    on_clause = " AND ".join([f"T.{m} = S.{m}" for m in merge_on])
    update_clause = ",\n            ".join([f"T.{u} = S.{u}" for u in merge_updates])

    merge_sql = f"""
        MERGE `{table_id}` T
        USING `{temp_table}` S
        ON {on_clause}
        WHEN MATCHED THEN UPDATE SET
            {update_clause}
        WHEN NOT MATCHED THEN INSERT ROW
    """
    client.query(merge_sql).result()
    client.delete_table(temp_table, not_found_ok=True)
    return len(rows)


# ─── Main ──────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dias", type=int, default=1)
    parser.add_argument("--data-inicial", type=str, default=None)
    parser.add_argument("--data-final", type=str, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limpar-checkpoint", action="store_true")
    args = parser.parse_args()

    hoje = datetime.now(timezone.utc)
    data_final_dt   = datetime.strptime(args.data_final,   "%Y%m%d") if args.data_final   else hoje
    data_inicial_dt = datetime.strptime(args.data_inicial, "%Y%m%d") if args.data_inicial else (data_final_dt - timedelta(days=args.dias - 1))
    data_inicial = data_inicial_dt.strftime("%Y%m%d")
    data_final   = data_final_dt.strftime("%Y%m%d")

    log.info(f"{'[DRY RUN] ' if args.dry_run else ''}Iniciando extracao PNCP: {data_inicial} -> {data_final}")

    bq = get_bq_client()
    ensure_tables_exist(bq)

    if args.limpar_checkpoint:
        clear_checkpoint(data_final)

    cp = load_checkpoint(data_final)
    pagina           = cp["proxima_pagina"]
    total_paginas    = cp["total_paginas"]
    registros_salvos = cp["registros_salvos"]
    itens_salvos     = cp.get("itens_salvos", 0)
    paginas_com_erro = cp.get("paginas_com_erro", [])

    log.info(f"Iniciando da pagina {pagina} | Compras salvas: {registros_salvos} | Itens salvos: {itens_salvos}")

    while True:
        log.info(f"  Pagina {pagina}" + (f"/{total_paginas}" if total_paginas else "") + "...")
        data = fetch_pagina_com_retry(data_final, pagina)

        if data is None:
            if total_paginas and pagina <= total_paginas:
                log.warning(f"  Pagina {pagina} falhou permanentemente. Pulando.")
                paginas_com_erro.append(pagina)
                save_checkpoint(data_final, pagina + 1, total_paginas, registros_salvos, itens_salvos, paginas_com_erro)
                pagina += 1
                time.sleep(REQUEST_DELAY)
                continue
            else:
                break

        if isinstance(data, dict):
            items = data.get("data", [])
            if not total_paginas:
                total_paginas = data.get("totalPaginas") or data.get("totalPages")
        elif isinstance(data, list):
            items = data
        else:
            items = []

        if not items:
            break

        rows = [r for raw in items if (r := transform(raw)) is not None]
        log.info(f"  {len(items)} compras recebidas | {len(rows)} validas")

        # Busca itens concorrentemente
        all_items_rows = []
        if rows:
            with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                results = executor.map(worker_fetch_itens, rows)
                for res in results:
                    all_items_rows.extend(res)
        
        log.info(f"  Baixados {len(all_items_rows)} itens vinculados.")

        if rows:
            # Upsert Compras
            registros_salvos += upsert_lote(
                rows, bq, TABLE_ID, BQ_SCHEMA,
                merge_on=["numeroControlePNCPCompra"],
                merge_updates=["situacaoCompraId", "situacaoCompraNome", "valorTotalEstimado", "valorTotalHomologado", "dataEncerramentoProposta", "objetoCompra", "informacaoComplementar", "updated_at"],
                dry_run=args.dry_run
            )
            # Upsert Itens
            itens_salvos += upsert_lote(
                all_items_rows, bq, TABLE_ID_ITENS, BQ_SCHEMA_ITENS,
                merge_on=["numeroControlePNCPCompra", "numeroItem"],
                merge_updates=["descricao", "quantidade", "valorUnitarioEstimado", "valorTotal", "unidadeMedida", "situacaoItem", "updated_at"],
                dry_run=args.dry_run
            )

        save_checkpoint(data_final, pagina + 1, total_paginas, registros_salvos, itens_salvos, paginas_com_erro)

        if total_paginas and pagina >= total_paginas:
            break

        pagina += 1
        time.sleep(REQUEST_DELAY)

    log.info("=" * 60)
    log.info("Extracao concluida!")
    log.info(f"  Total compras salvas: {registros_salvos}")
    log.info(f"  Total itens salvos:   {itens_salvos}")
    if paginas_com_erro:
        log.warning(f"  Paginas com erro (puladas): {paginas_com_erro}")
    else:
        clear_checkpoint(data_final)
    log.info("=" * 60)

if __name__ == "__main__":
    main()
