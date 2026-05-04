"""
update_oportunidades.py — Pipeline Diário de Oportunidades PNCP

Consulta a API do PNCP para listar compras com proposta em aberto
e faz upsert incremental na tabela `compras_abertas` do BigQuery.

Funcionalidades:
  - Checkpoint automático: retoma do ponto de parada em caso de interrupção
  - Upsert por lote: salva no BigQuery a cada página (não perde dados)
  - Retry com backoff: 3 tentativas por página com espera exponencial
  - Credenciais via GOOGLE_CREDENTIALS_JSON (mesmo padrão do app Flask)

Uso:
    python scripts/update_oportunidades.py
    python scripts/update_oportunidades.py --dias 7
    python scripts/update_oportunidades.py --data-inicial 20260101 --data-final 20260131
    python scripts/update_oportunidades.py --dry-run
    python scripts/update_oportunidades.py --limpar-checkpoint  (força restart do zero)

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
from pathlib import Path

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

PNCP_BASE_URL   = "https://pncp.gov.br/api/consulta/v1"
PAGE_SIZE       = 50    # Tamanho de página da API PNCP
REQUEST_DELAY   = 3     # Segundos entre requisições
MAX_RETRIES     = 3     # Tentativas por página
RETRY_BACKOFF   = 2     # Fator de backoff: 2s, 4s, 8s

CHECKPOINT_DIR  = Path(__file__).parent  # mesma pasta do script


# ─── Credenciais BigQuery ──────────────────────────────────────────────────────
def get_bq_client() -> bigquery.Client:
    """
    Cria um cliente BigQuery usando GOOGLE_CREDENTIALS_JSON (mesmo padrão do app Flask).
    Fallback para Application Default Credentials.
    """
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
    """Carrega o checkpoint da execução anterior, se existir."""
    cp = checkpoint_path(data_final)
    if cp.exists():
        try:
            data = json.loads(cp.read_text())
            log.info(
                f"Checkpoint encontrado: retomando da pagina {data['proxima_pagina']} "
                f"({data['registros_salvos']} registros ja salvos)"
            )
            return data
        except Exception as e:
            log.warning(f"Checkpoint invalido, ignorando: {e}")
    return {"proxima_pagina": 1, "total_paginas": None, "registros_salvos": 0, "paginas_com_erro": []}


def save_checkpoint(data_final: str, proxima_pagina: int, total_paginas, registros_salvos: int, paginas_com_erro: list):
    """Persiste o checkpoint após cada página bem-sucedida."""
    cp = checkpoint_path(data_final)
    data = {
        "proxima_pagina":   proxima_pagina,
        "total_paginas":    total_paginas,
        "registros_salvos": registros_salvos,
        "paginas_com_erro": paginas_com_erro,
        "atualizado_em":    datetime.now(timezone.utc).isoformat(),
    }
    cp.write_text(json.dumps(data, ensure_ascii=False, indent=2))


def clear_checkpoint(data_final: str):
    """Remove o checkpoint ao concluir com sucesso."""
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
)
OPTIONS (
    description = "Compras abertas extraidas da API PNCP - atualizacao diaria"
)
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


def ensure_table_exists(client: bigquery.Client):
    """Cria a tabela se não existir."""
    try:
        client.query(CREATE_TABLE_SQL).result()
        log.info("Tabela compras_abertas verificada/criada.")
    except Exception as e:
        log.error(f"Erro ao criar tabela: {e}")
        raise


# ─── Funções de API ────────────────────────────────────────────────────────────
def fetch_pagina(data_final: str, pagina: int, timeout: int = 60) -> dict:
    """Consulta uma página da API PNCP com timeout explícito."""
    url = f"{PNCP_BASE_URL}/contratacoes/proposta"
    params = {
        "dataFinal":     data_final,
        "pagina":        pagina,
        "tamanhoPagina": PAGE_SIZE,
    }
    resp = requests.get(url, params=params, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def fetch_pagina_com_retry(data_final: str, pagina: int):
    """
    Tenta buscar uma página com MAX_RETRIES tentativas e backoff exponencial.
    Retorna None se todas as tentativas falharem.
    """
    for tentativa in range(1, MAX_RETRIES + 1):
        try:
            return fetch_pagina(data_final, pagina)
        except requests.HTTPError as e:
            if e.response.status_code == 404:
                log.info(f"  Pagina {pagina}: 404 (fim dos dados).")
                return None
            wait = RETRY_BACKOFF ** tentativa
            log.warning(
                f"  Pagina {pagina}: HTTP {e.response.status_code} — "
                f"tentativa {tentativa}/{MAX_RETRIES}, aguardando {wait}s..."
            )
            time.sleep(wait)
        except (requests.ConnectionError, requests.Timeout) as e:
            wait = RETRY_BACKOFF ** tentativa
            log.warning(
                f"  Pagina {pagina}: conexao falhou ({type(e).__name__}) — "
                f"tentativa {tentativa}/{MAX_RETRIES}, aguardando {wait}s..."
            )
            time.sleep(wait)
        except Exception as e:
            log.error(f"  Pagina {pagina}: erro inesperado: {e}")
            break

    log.error(f"  Pagina {pagina}: falhou apos {MAX_RETRIES} tentativas. Sera pulada.")
    return None


# ─── Transformação ─────────────────────────────────────────────────────────────
def transform(raw: dict):
    """Normaliza um item da API PNCP para o schema BigQuery. Retorna None se inválido."""
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

    orgao   = raw.get("orgaoEntidade") or {}
    unidade = raw.get("unidadeOrgao") or {}
    numero  = raw.get("numeroControlePNCP") or raw.get("numeroControlePNCPCompra") or ""

    if not numero:
        return None  # Registro inválido, descarta

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


# ─── BigQuery: Upsert por lote ─────────────────────────────────────────────────
def upsert_lote(rows: list, client: bigquery.Client, dry_run: bool = False) -> int:
    """
    Faz upsert de um lote via tabela temporária + MERGE.
    Salva imediatamente — não acumula em RAM.
    Retorna a quantidade de registros processados.
    """
    if not rows:
        return 0

    if dry_run:
        log.info(f"  [DRY RUN] {len(rows)} registros (nao salvos)")
        return len(rows)

    temp_table = f"{GCP_PROJECT_ID}.{GCP_DATASET_ID}.compras_abertas_tmp"

    # 1. Carrega lote na temp (WRITE_TRUNCATE — substitui completamente)
    job_config = bigquery.LoadJobConfig(
        write_disposition="WRITE_TRUNCATE",
        source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
        schema=BQ_SCHEMA,
    )
    load_job = client.load_table_from_json(rows, temp_table, job_config=job_config)
    load_job.result()

    # 2. MERGE temp → tabela principal (upsert real, sem streaming buffer)
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
            T.objetoCompra              = S.objetoCompra,
            T.informacaoComplementar    = S.informacaoComplementar,
            T.updated_at                = S.updated_at
        WHEN NOT MATCHED THEN INSERT ROW
    """
    client.query(merge_sql).result()

    # 3. Limpa a temporária
    client.delete_table(temp_table, not_found_ok=True)

    log.info(f"  Lote salvo: {len(rows)} registros no BigQuery")
    return len(rows)


# ─── Main ──────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Pipeline de Oportunidades PNCP")
    parser.add_argument("--dias", type=int, default=1,
                        help="Quantos dias retroativos buscar (padrao: 1 = hoje)")
    parser.add_argument("--data-inicial", type=str, default=None,
                        help="Data inicial no formato YYYYMMDD (sobrepoem --dias)")
    parser.add_argument("--data-final", type=str, default=None,
                        help="Data final no formato YYYYMMDD (padrao: hoje)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Apenas exibe os dados, nao salva no BigQuery")
    parser.add_argument("--limpar-checkpoint", action="store_true",
                        help="Ignora checkpoint existente e reinicia do zero")
    args = parser.parse_args()

    hoje = datetime.now(timezone.utc)
    data_final_dt   = datetime.strptime(args.data_final,   "%Y%m%d") if args.data_final   else hoje
    data_inicial_dt = datetime.strptime(args.data_inicial, "%Y%m%d") if args.data_inicial else (data_final_dt - timedelta(days=args.dias - 1))

    data_inicial = data_inicial_dt.strftime("%Y%m%d")
    data_final   = data_final_dt.strftime("%Y%m%d")

    log.info(f"{'[DRY RUN] ' if args.dry_run else ''}Iniciando extracao PNCP: {data_inicial} -> {data_final}")

    # BigQuery (com credenciais via GOOGLE_CREDENTIALS_JSON)
    bq = get_bq_client()
    ensure_table_exists(bq)

    # Checkpoint: retoma de onde parou (ou começa do zero)
    if args.limpar_checkpoint:
        clear_checkpoint(data_final)

    cp               = load_checkpoint(data_final)
    pagina           = cp["proxima_pagina"]
    total_paginas    = cp["total_paginas"]
    registros_salvos = cp["registros_salvos"]
    paginas_com_erro = cp.get("paginas_com_erro", [])

    log.info(
        f"Iniciando da pagina {pagina}"
        + (f"/{total_paginas}" if total_paginas else "")
        + f" | Ja salvos: {registros_salvos}"
    )

    # ─── Loop principal: busca e salva 1 página por vez ───────────────────────
    while True:
        log.info(
            f"  Pagina {pagina}"
            + (f"/{total_paginas}" if total_paginas else "")
            + "..."
        )

        data = fetch_pagina_com_retry(data_final, pagina)

        # None = 404 ou falha total
        if data is None:
            if total_paginas and pagina <= total_paginas:
                # Erro em página intermediária: pula e continua
                log.warning(f"  Pagina {pagina} falhou permanentemente. Pulando.")
                paginas_com_erro.append(pagina)
                save_checkpoint(data_final, pagina + 1, total_paginas, registros_salvos, paginas_com_erro)
                pagina += 1
                time.sleep(REQUEST_DELAY)
                continue
            else:
                log.info("  Fim dos dados (sem mais paginas).")
                break

        # Extrai itens da resposta
        if isinstance(data, dict):
            items = data.get("data", [])
            # Atualiza total de páginas na primeira vez
            if not total_paginas:
                total_paginas = data.get("totalPaginas") or data.get("totalPages")
                if total_paginas:
                    log.info(f"  Total de paginas detectado: {total_paginas}")
        elif isinstance(data, list):
            items = data
        else:
            items = []

        if not items:
            log.info("  Pagina vazia — fim dos dados.")
            break

        # Transforma registros (filtra inválidos)
        rows = [r for raw in items if (r := transform(raw)) is not None]
        log.info(f"  {len(items)} itens recebidos | {len(rows)} validos")

        # Exibe exemplo no dry-run (só na primeira página nova)
        if args.dry_run and rows and pagina == cp["proxima_pagina"]:
            log.info(f"  [DRY RUN] Exemplo: {json.dumps(rows[0], ensure_ascii=False, indent=2)}")

        # Upsert IMEDIATO — não perde dados se travar depois
        if rows:
            registros_salvos += upsert_lote(rows, bq, dry_run=args.dry_run)

        # Salva checkpoint ANTES de avançar para próxima página
        save_checkpoint(data_final, pagina + 1, total_paginas, registros_salvos, paginas_com_erro)

        # Verifica fim
        if total_paginas and pagina >= total_paginas:
            log.info(f"  Ultima pagina ({pagina}/{total_paginas}) concluida.")
            break

        pagina += 1
        time.sleep(REQUEST_DELAY)

    # ─── Sumário final ─────────────────────────────────────────────────────────
    log.info("=" * 60)
    log.info(f"Extracao concluida!")
    log.info(f"  Total de registros salvos: {registros_salvos}")
    if paginas_com_erro:
        log.warning(f"  Paginas com erro (puladas): {paginas_com_erro}")
        log.info("  Checkpoint mantido. Re-execute para tentar as paginas com erro.")
    else:
        clear_checkpoint(data_final)
    log.info("=" * 60)


if __name__ == "__main__":
    main()
