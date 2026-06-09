"""
Script otimizado para popular a tabela resultados no BigQuery
Busca itens no BigQuery, consulta a API PNCP, e grava resultados no BigQuery.
Com suporte a retomada (checkpoint) e processamento paralelo.
"""
import os
import sys
import requests
from datetime import datetime
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from google.cloud import bigquery
from app.utils_bigquery import bq_client

# Configurações
BATCH_SIZE = 100
MAX_WORKERS = 5  # Número de threads paralelas
RATE_LIMIT_DELAY = 0.1  # Delay entre requisições (100ms)
CHECKPOINT_FILE = 'populate_checkpoint.json'
INSERT_BATCH_SIZE = 500  # Quantos resultados acumular antes de gravar no BigQuery


def get_bq_client():
    """Retorna o cliente BigQuery e referências do projeto/dataset."""
    client = bq_client.get_client()
    project_id = bq_client.project_id
    dataset_id = bq_client.dataset_id
    return client, project_id, dataset_id


def load_checkpoint():
    """Carrega o checkpoint do último processamento"""
    if os.path.exists(CHECKPOINT_FILE):
        with open(CHECKPOINT_FILE, 'r') as f:
            return json.load(f)
    return {'last_processed_id': 0, 'total_inserted': 0}


def save_checkpoint(last_id, total_inserted):
    """Salva o checkpoint atual"""
    with open(CHECKPOINT_FILE, 'w') as f:
        json.dump({
            'last_processed_id': last_id,
            'total_inserted': total_inserted,
            'timestamp': datetime.now().isoformat()
        }, f)


def get_resultados_from_api(cnpj, ano, sequencial, numero_item):
    """Busca resultados de um item específico na API PNCP"""
    url = f"https://pncp.gov.br/api/pncp/v1/orgaos/{cnpj}/compras/{ano}/{sequencial}/itens/{numero_item}/resultados"
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            return response.json()
        elif response.status_code == 404:
            return []  # Sem resultados
        else:
            return None  # Erro - tentar novamente
    except Exception as e:
        return None  # Erro - tentar novamente


def parse_numero_controle(numero_controle):
    """Extrai CNPJ, ano e sequencial do numeroControlePNCPCompra"""
    try:
        parts = numero_controle.split('/')
        if len(parts) != 2:
            return None, None, None
            
        ano_part = parts[1]
        ano = ano_part.split('-')[0] if '-' in ano_part else ano_part
        
        before_slash = parts[0]
        dash_parts = before_slash.split('-')
        
        if len(dash_parts) < 3:
            return None, None, None
        
        cnpj = dash_parts[0]
        sequencial = dash_parts[2]
        
        return cnpj, ano, sequencial
    except Exception as e:
        return None, None, None


def process_item(item_data):
    """Processa um único item e retorna os resultados"""
    item_id, parent_cnpj, numero_controle, numero_item = item_data
    
    cnpj, ano, sequencial = parse_numero_controle(numero_controle)
    if not cnpj or not ano or not sequencial:
        return item_id, []
    
    time.sleep(RATE_LIMIT_DELAY)  # Rate limiting
    resultados = get_resultados_from_api(cnpj, ano, sequencial, numero_item)
    
    if resultados is None:
        return item_id, None  # Erro - tentar novamente
    
    return item_id, resultados


def _safe_int(value, default=None):
    """Converte valor para int de forma segura."""
    if value is None:
        return default
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


def _safe_float(value, default=None):
    """Converte valor para float de forma segura."""
    if value is None:
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def _safe_str(value, default=None):
    """Converte valor para string de forma segura."""
    if value is None:
        return default
    return str(value)


def _safe_date(value):
    """Extrai a parte da data (YYYY-MM-DD) de um valor datetime string."""
    if value is None:
        return None
    s = str(value)
    return s[:10] if len(s) >= 10 else s


def _safe_timestamp(value):
    """Converte valor para timestamp ISO string para BigQuery."""
    if value is None:
        return None
    s = str(value)
    # BigQuery aceita formato ISO 8601
    return s


def map_resultado_to_bq_row(numero_controle, resultado):
    """
    Mapeia um resultado da API PNCP (camelCase) para o schema
    da tabela resultados no BigQuery (lowercase).
    """
    return {
        "numerocontrolepncpcompra": numero_controle,
        "numeroitem": _safe_int(resultado.get('numeroItem')),
        "sequencialresultado": _safe_int(resultado.get('sequencialResultado')),
        "nifornecedor": _safe_int(resultado.get('niFornecedor')),
        "nomerazaosocialfornecedor": _safe_str(resultado.get('nomeRazaoSocialFornecedor')),
        "tipopessoa": _safe_str(resultado.get('tipoPessoa')),
        "portefornecedorid": _safe_int(resultado.get('porteFornecedorId')),
        "portefornecedornome": _safe_str(resultado.get('porteFornecedorNome')),
        "valorunitariohomologado": _safe_float(resultado.get('valorUnitarioHomologado')),
        "quantidadehomologada": _safe_float(resultado.get('quantidadeHomologada')),
        "valortotalhomologado": _safe_float(resultado.get('valorTotalHomologado')),
        "percentualdesconto": _safe_float(resultado.get('percentualDesconto')),
        "situacaocompraitemresultadoid": _safe_int(resultado.get('situacaoCompraItemResultadoId')),
        "situacaocompraitemresultadonome": _safe_str(resultado.get('situacaoCompraItemResultadoNome')),
        "dataresultado": _safe_date(resultado.get('dataResultado')),
        "datainclusao": _safe_timestamp(resultado.get('dataInclusao')),
        "dataatualizacao": _safe_timestamp(resultado.get('dataAtualizacao')),
        "ordemclassificacaosrp": _safe_str(resultado.get('ordemClassificacaoSrp')),
        "indicadorsubcontratacao": resultado.get('indicadorSubcontratacao'),
        "aplicacaomargempreferencia": resultado.get('aplicacaoMargemPreferencia'),
        "aplicacaobeneficiomeepp": resultado.get('aplicacaoBeneficioMeEpp'),
        "aplicacaocriteriodesempate": resultado.get('aplicacaoCriterioDesempate'),
        "motivocancelamento": _safe_str(resultado.get('motivoCancelamento')),
        "datacancelamento": _safe_str(resultado.get('dataCancelamento')),
        "codigopais": _safe_str(resultado.get('codigoPais')),
        "paisorigemprodutoservico": _safe_str(resultado.get('paisOrigemProdutoServico')),
        "naturezajuridicaid": _safe_str(resultado.get('naturezaJuridicaId')),
        "naturezajuridicanome": _safe_str(resultado.get('naturezaJuridicaNome')),
        "amparolegalmargempreferencia": _safe_str(resultado.get('amparoLegalMargemPreferencia')),
        "amparolegalcriteriodesempate": _safe_str(resultado.get('amparoLegalCriterioDesempate')),
        "moedaestrangeira": _safe_str(resultado.get('moedaEstrangeira')),
        "valornominalmoedaestrangeira": _safe_str(resultado.get('valorNominalMoedaEstrangeira')),
        "datacotacaomoedaestrangeira": _safe_str(resultado.get('dataCotacaoMoedaEstrangeira')),
        "timezonecotacaomoedaestrangeira": _safe_str(resultado.get('timezoneCotacaoMoedaEstrangeira')),
    }


def insert_resultados_batch_bq(client, project_id, dataset_id, rows):
    """
    Insere um lote de resultados no BigQuery usando MERGE para evitar duplicatas.
    Usa tabela temporária + MERGE para simular upsert.
    """
    if not rows:
        return 0

    table_id = f"{project_id}.{dataset_id}.resultados"
    temp_suffix = datetime.now().strftime('%Y%m%d%H%M%S%f')
    temp_table_id = f"{project_id}.{dataset_id}._temp_resultados_{temp_suffix}"

    try:
        # 1. Carregar dados na tabela temporária
        job_config = bigquery.LoadJobConfig(
            write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
            autodetect=False,
            schema=[
                bigquery.SchemaField("numerocontrolepncpcompra", "STRING"),
                bigquery.SchemaField("numeroitem", "INTEGER"),
                bigquery.SchemaField("sequencialresultado", "INTEGER"),
                bigquery.SchemaField("nifornecedor", "INTEGER"),
                bigquery.SchemaField("nomerazaosocialfornecedor", "STRING"),
                bigquery.SchemaField("tipopessoa", "STRING"),
                bigquery.SchemaField("portefornecedorid", "INTEGER"),
                bigquery.SchemaField("portefornecedornome", "STRING"),
                bigquery.SchemaField("valorunitariohomologado", "FLOAT"),
                bigquery.SchemaField("quantidadehomologada", "FLOAT"),
                bigquery.SchemaField("valortotalhomologado", "FLOAT"),
                bigquery.SchemaField("percentualdesconto", "FLOAT"),
                bigquery.SchemaField("situacaocompraitemresultadoid", "INTEGER"),
                bigquery.SchemaField("situacaocompraitemresultadonome", "STRING"),
                bigquery.SchemaField("dataresultado", "DATE"),
                bigquery.SchemaField("datainclusao", "TIMESTAMP"),
                bigquery.SchemaField("dataatualizacao", "TIMESTAMP"),
                bigquery.SchemaField("ordemclassificacaosrp", "STRING"),
                bigquery.SchemaField("indicadorsubcontratacao", "BOOLEAN"),
                bigquery.SchemaField("aplicacaomargempreferencia", "BOOLEAN"),
                bigquery.SchemaField("aplicacaobeneficiomeepp", "BOOLEAN"),
                bigquery.SchemaField("aplicacaocriteriodesempate", "BOOLEAN"),
                bigquery.SchemaField("motivocancelamento", "STRING"),
                bigquery.SchemaField("datacancelamento", "STRING"),
                bigquery.SchemaField("codigopais", "STRING"),
                bigquery.SchemaField("paisorigemprodutoservico", "STRING"),
                bigquery.SchemaField("naturezajuridicaid", "STRING"),
                bigquery.SchemaField("naturezajuridicanome", "STRING"),
                bigquery.SchemaField("amparolegalmargempreferencia", "STRING"),
                bigquery.SchemaField("amparolegalcriteriodesempate", "STRING"),
                bigquery.SchemaField("moedaestrangeira", "STRING"),
                bigquery.SchemaField("valornominalmoedaestrangeira", "STRING"),
                bigquery.SchemaField("datacotacaomoedaestrangeira", "STRING"),
                bigquery.SchemaField("timezonecotacaomoedaestrangeira", "STRING"),
            ],
        )

        load_job = client.load_table_from_json(rows, temp_table_id, job_config=job_config)
        load_job.result()  # Aguardar conclusão

        # 2. MERGE: atualiza existentes e insere novos
        merge_sql = f"""
            MERGE `{table_id}` AS target
            USING `{temp_table_id}` AS source
            ON target.numerocontrolepncpcompra = source.numerocontrolepncpcompra
               AND target.numeroitem = source.numeroitem
               AND target.sequencialresultado = source.sequencialresultado
            WHEN MATCHED THEN
                UPDATE SET
                    nomerazaosocialfornecedor = source.nomerazaosocialfornecedor,
                    valorunitariohomologado = source.valorunitariohomologado,
                    valortotalhomologado = source.valortotalhomologado,
                    dataatualizacao = source.dataatualizacao
            WHEN NOT MATCHED THEN
                INSERT (
                    numerocontrolepncpcompra, numeroitem, sequencialresultado,
                    nifornecedor, nomerazaosocialfornecedor, tipopessoa,
                    portefornecedorid, portefornecedornome,
                    valorunitariohomologado, quantidadehomologada, valortotalhomologado,
                    percentualdesconto, situacaocompraitemresultadoid, situacaocompraitemresultadonome,
                    dataresultado, datainclusao, dataatualizacao,
                    ordemclassificacaosrp, indicadorsubcontratacao,
                    aplicacaomargempreferencia, aplicacaobeneficiomeepp, aplicacaocriteriodesempate,
                    motivocancelamento, datacancelamento, codigopais, paisorigemprodutoservico,
                    naturezajuridicaid, naturezajuridicanome,
                    amparolegalmargempreferencia, amparolegalcriteriodesempate,
                    moedaestrangeira, valornominalmoedaestrangeira, datacotacaomoedaestrangeira,
                    timezonecotacaomoedaestrangeira
                )
                VALUES (
                    source.numerocontrolepncpcompra, source.numeroitem, source.sequencialresultado,
                    source.nifornecedor, source.nomerazaosocialfornecedor, source.tipopessoa,
                    source.portefornecedorid, source.portefornecedornome,
                    source.valorunitariohomologado, source.quantidadehomologada, source.valortotalhomologado,
                    source.percentualdesconto, source.situacaocompraitemresultadoid, source.situacaocompraitemresultadonome,
                    source.dataresultado, source.datainclusao, source.dataatualizacao,
                    source.ordemclassificacaosrp, source.indicadorsubcontratacao,
                    source.aplicacaomargempreferencia, source.aplicacaobeneficiomeepp, source.aplicacaocriteriodesempate,
                    source.motivocancelamento, source.datacancelamento, source.codigopais, source.paisorigemprodutoservico,
                    source.naturezajuridicaid, source.naturezajuridicanome,
                    source.amparolegalmargempreferencia, source.amparolegalcriteriodesempate,
                    source.moedaestrangeira, source.valornominalmoedaestrangeira, source.datacotacaomoedaestrangeira,
                    source.timezonecotacaomoedaestrangeira
                )
        """
        merge_job = client.query(merge_sql)
        result = merge_job.result()

        # Pegar contagem de linhas modificadas
        inserted = merge_job.num_dml_affected_rows or len(rows)

        return inserted

    except Exception as e:
        print(f"Erro ao inserir lote no BigQuery: {e}")
        return 0

    finally:
        # 3. Limpar tabela temporária
        try:
            client.delete_table(temp_table_id, not_found_ok=True)
        except Exception:
            pass


def populate_all_resultados():
    """Popula todos os resultados em lotes com processamento paralelo"""
    client, project_id, dataset_id = get_bq_client()

    checkpoint = load_checkpoint()
    last_id = checkpoint['last_processed_id']
    total_inserted = checkpoint['total_inserted']
    
    print(f"Iniciando população a partir do ID {last_id}")
    print(f"Total já inserido: {total_inserted}")
    print(f"Fonte de dados: BigQuery ({project_id}.{dataset_id}.itens)")
    print(f"Destino: BigQuery ({project_id}.{dataset_id}.resultados)")
    
    while True:
        # Buscar próximo lote de itens no BigQuery
        query = f"""
            SELECT DISTINCT
                id,
                parent_cnpj,
                parent_numeroControlePNCPAta AS numeroControlePNCPCompra,
                numeroItem
            FROM `{project_id}.{dataset_id}.itens`
            WHERE temResultado = TRUE
              AND id > @last_id
            ORDER BY id
            LIMIT @batch_size
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("last_id", "INT64", last_id),
                bigquery.ScalarQueryParameter("batch_size", "INT64", BATCH_SIZE),
            ]
        )

        query_job = client.query(query, job_config=job_config)
        batch = []
        for row in query_job.result():
            batch.append((row['id'], row['parent_cnpj'], row['numeroControlePNCPCompra'], row['numeroItem']))
        
        if not batch:
            print("✅ Todos os itens foram processados!")
            break
        
        print(f"\nProcessando lote de {len(batch)} itens (ID {batch[0][0]} a {batch[-1][0]})...")
        
        # Processar em paralelo
        resultados_to_insert = []
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {executor.submit(process_item, item): item for item in batch}
            
            for future in as_completed(futures):
                item_id, resultados = future.result()
                
                if resultados is not None and resultados:
                    item_data = futures[future]
                    numero_controle = item_data[2]
                    
                    for resultado in resultados:
                        bq_row = map_resultado_to_bq_row(numero_controle, resultado)
                        resultados_to_insert.append(bq_row)
        
        # Inserir lote no BigQuery via MERGE
        inserted_count = insert_resultados_batch_bq(client, project_id, dataset_id, resultados_to_insert)
        total_inserted += inserted_count
        last_id = batch[-1][0]
        
        # Salvar checkpoint
        save_checkpoint(last_id, total_inserted)
        
        print(f"✅ Lote processado: {inserted_count} resultados inseridos/atualizados")
        print(f"📊 Total acumulado: {total_inserted} resultados")
        print(f"🔖 Checkpoint salvo: último ID = {last_id}")
    
    print(f"\n🎉 Finalizado! Total de resultados inseridos: {total_inserted}")


if __name__ == "__main__":
    populate_all_resultados()
