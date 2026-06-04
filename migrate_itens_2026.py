"""
migrate_itens_2026.py
=====================
Carrega o arquivo itens_consolidado_2026_padronizado.csv para a tabela
`itens` no BigQuery utilizando uma tabela de staging temporária.

Estratégia (zero downtime, zero perda de dados):
  1. Cria tabela staging `itens_staging_2026` com as 38 colunas do CSV (sem `id`)
  2. Faz upload do CSV para a tabela staging
  3. Lê o MAX(id) atual da tabela principal `itens`
  4. Insere os dados do staging na tabela principal calculando novos IDs sequenciais
     como: MAX_ID + ROW_NUMBER() OVER (ORDER BY parent_numeroControlePNCPAta, numeroItem)
  5. Deleta a tabela staging temporária
  6. Valida o total de linhas inseridas

Segurança:
  - NUNCA apaga nem modifica linhas existentes na tabela `itens`
  - A tabela staging é descartável e não interfere em produção
  - Testa com 10 linhas antes de executar o arquivo completo
"""

import os
import json
import base64
import time
import sys
from google.cloud import bigquery
from google.oauth2.credentials import Credentials

# ─── Configuração ──────────────────────────────────────────────────────────────
PROJECT_ID  = os.environ.get('GCP_PROJECT_ID', 'pncp-466018')
DATASET_ID  = 'pncp_data'
MAIN_TABLE  = f'{PROJECT_ID}.{DATASET_ID}.itens'
STAGING_TABLE = f'{PROJECT_ID}.{DATASET_ID}.itens_staging_2026'
CSV_PATH    = 'CSVs/itens_consolidado_2026_padronizado.csv'
TEST_CSV_PATH = 'CSVs/itens_2026_test_10rows.csv'


# Schema das 38 colunas do CSV (sem a coluna `id` que é calculada)
STAGING_SCHEMA = [
    bigquery.SchemaField("numeroItem",                         "INTEGER",  mode="NULLABLE"),
    bigquery.SchemaField("descricao",                          "STRING",   mode="NULLABLE"),
    bigquery.SchemaField("materialOuServico",                  "STRING",   mode="NULLABLE"),
    bigquery.SchemaField("materialOuServicoNome",              "STRING",   mode="NULLABLE"),
    bigquery.SchemaField("valorUnitarioEstimado",              "FLOAT",    mode="NULLABLE"),
    bigquery.SchemaField("valorTotal",                         "FLOAT",    mode="NULLABLE"),
    bigquery.SchemaField("quantidade",                         "FLOAT",    mode="NULLABLE"),
    bigquery.SchemaField("unidadeMedida",                      "STRING",   mode="NULLABLE"),
    bigquery.SchemaField("orcamentoSigiloso",                  "BOOLEAN",  mode="NULLABLE"),
    bigquery.SchemaField("itemCategoriaId",                    "INTEGER",  mode="NULLABLE"),
    bigquery.SchemaField("itemCategoriaNome",                  "STRING",   mode="NULLABLE"),
    bigquery.SchemaField("patrimonio",                         "STRING",   mode="NULLABLE"),
    bigquery.SchemaField("codigoRegistroImobiliario",          "STRING",   mode="NULLABLE"),
    bigquery.SchemaField("criterioJulgamentoId",               "INTEGER",  mode="NULLABLE"),
    bigquery.SchemaField("criterioJulgamentoNome",             "STRING",   mode="NULLABLE"),
    bigquery.SchemaField("situacaoCompraItem",                 "INTEGER",  mode="NULLABLE"),
    bigquery.SchemaField("situacaoCompraItemNome",             "STRING",   mode="NULLABLE"),
    bigquery.SchemaField("tipoBeneficio",                      "FLOAT",    mode="NULLABLE"),
    bigquery.SchemaField("tipoBeneficioNome",                  "STRING",   mode="NULLABLE"),
    bigquery.SchemaField("incentivoProdutivoBasico",           "BOOLEAN",  mode="NULLABLE"),
    bigquery.SchemaField("dataInclusao",                       "TIMESTAMP","NULLABLE"),
    bigquery.SchemaField("dataAtualizacao",                    "TIMESTAMP","NULLABLE"),
    bigquery.SchemaField("temResultado",                       "BOOLEAN",  mode="NULLABLE"),
    bigquery.SchemaField("imagem",                             "INTEGER",  mode="NULLABLE"),
    bigquery.SchemaField("aplicabilidadeMargemPreferenciaNormal",   "BOOLEAN", mode="NULLABLE"),
    bigquery.SchemaField("aplicabilidadeMargemPreferenciaAdicional","BOOLEAN", mode="NULLABLE"),
    bigquery.SchemaField("percentualMargemPreferenciaNormal",       "STRING",  mode="NULLABLE"),
    bigquery.SchemaField("percentualMargemPreferenciaAdicional",    "STRING",  mode="NULLABLE"),
    bigquery.SchemaField("ncmNbsCodigo",                       "STRING",   mode="NULLABLE"),
    bigquery.SchemaField("ncmNbsDescricao",                    "STRING",   mode="NULLABLE"),
    bigquery.SchemaField("catalogo",                           "STRING",   mode="NULLABLE"),
    bigquery.SchemaField("categoriaItemCatalogo",              "STRING",   mode="NULLABLE"),
    bigquery.SchemaField("catalogoCodigoItem",                 "STRING",   mode="NULLABLE"),
    bigquery.SchemaField("informacaoComplementar",             "STRING",   mode="NULLABLE"),
    bigquery.SchemaField("tipoMargemPreferencia",              "STRING",   mode="NULLABLE"),
    bigquery.SchemaField("exigenciaConteudoNacional",          "BOOLEAN",  mode="NULLABLE"),
    bigquery.SchemaField("parent_cnpj",                        "INTEGER",  mode="NULLABLE"),
    bigquery.SchemaField("parent_numeroControlePNCPAta",       "STRING",   mode="NULLABLE"),
]


def get_credentials() -> Credentials:
    """Carrega credenciais do .env ou ADC."""
    creds_b64 = os.environ.get('GOOGLE_CREDENTIALS_JSON', '')
    if creds_b64:
        try:
            creds_json = json.loads(base64.b64decode(creds_b64).decode('utf-8'))
            if creds_json.get('type') == 'authorized_user':
                return Credentials(
                    token=None,
                    refresh_token=creds_json['refresh_token'],
                    client_id=creds_json['client_id'],
                    client_secret=creds_json['client_secret'],
                    token_uri='https://oauth2.googleapis.com/token'
                )
        except Exception as e:
            print(f"Aviso: falha ao ler GOOGLE_CREDENTIALS_JSON: {e}. Usando ADC.")
    return None  # Retorna None para usar ADC


def get_client() -> bigquery.Client:
    creds = get_credentials()
    if creds:
        return bigquery.Client(project=PROJECT_ID, credentials=creds)
    return bigquery.Client(project=PROJECT_ID)


def get_max_id(client: bigquery.Client) -> int:
    """Retorna o maior id atual da tabela principal."""
    result = next(client.query(f"SELECT MAX(id) as max_id FROM `{MAIN_TABLE}`").result())
    return result['max_id'] or 0


def get_row_count(client: bigquery.Client, table_id: str) -> int:
    """Retorna o total de linhas de uma tabela."""
    result = next(client.query(f"SELECT COUNT(*) as total FROM `{table_id}`").result())
    return result['total']


def delete_staging_if_exists(client: bigquery.Client):
    """Remove a tabela de staging se existir."""
    try:
        client.delete_table(STAGING_TABLE, not_found_ok=True)
        print(f"  Tabela staging removida: {STAGING_TABLE}")
    except Exception as e:
        print(f"  Aviso ao remover staging: {e}")


def create_staging_table(client: bigquery.Client):
    """Cria a tabela de staging com schema explícito."""
    delete_staging_if_exists(client)
    table = bigquery.Table(STAGING_TABLE, schema=STAGING_SCHEMA)
    client.create_table(table)
    print(f"  Tabela staging criada: {STAGING_TABLE}")


def load_csv_to_staging(client: bigquery.Client, csv_path: str):
    """Faz upload do CSV para a tabela de staging."""
    job_config = bigquery.LoadJobConfig(
        source_format=bigquery.SourceFormat.CSV,
        skip_leading_rows=1,
        schema=STAGING_SCHEMA,
        autodetect=False,
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
        allow_quoted_newlines=True,
        allow_jagged_rows=False,
    )

    print(f"  Carregando '{csv_path}' na tabela staging...")
    file_size = os.path.getsize(csv_path)
    print(f"  Tamanho do arquivo: {file_size / 1_073_741_824:.2f} GB")

    with open(csv_path, "rb") as source_file:
        job = client.load_table_from_file(source_file, STAGING_TABLE, job_config=job_config)

    print(f"  Job {job.job_id} iniciado, aguardando conclusão...")
    start = time.time()
    job.result()  # Aguarda conclusão
    elapsed = time.time() - start
    print(f"  Upload concluído em {elapsed:.1f}s | Linhas carregadas: {job.output_rows:,}")


def insert_staging_into_main(client: bigquery.Client, max_id: int):
    """
    Insere dados do staging na tabela principal com IDs sequenciais.
    Usa ROW_NUMBER() + max_id para calcular novos IDs únicos.
    """
    sql = f"""
        INSERT INTO `{MAIN_TABLE}` (
            id, numeroItem, descricao, materialOuServico, materialOuServicoNome,
            valorUnitarioEstimado, valorTotal, quantidade, unidadeMedida,
            orcamentoSigiloso, itemCategoriaId, itemCategoriaNome, patrimonio,
            codigoRegistroImobiliario, criterioJulgamentoId, criterioJulgamentoNome,
            situacaoCompraItem, situacaoCompraItemNome, tipoBeneficio, tipoBeneficioNome,
            incentivoProdutivoBasico, dataInclusao, dataAtualizacao, temResultado,
            imagem, aplicabilidadeMargemPreferenciaNormal, aplicabilidadeMargemPreferenciaAdicional,
            percentualMargemPreferenciaNormal, percentualMargemPreferenciaAdicional,
            ncmNbsCodigo, ncmNbsDescricao, catalogo, categoriaItemCatalogo,
            catalogoCodigoItem, informacaoComplementar, tipoMargemPreferencia,
            exigenciaConteudoNacional, parent_cnpj, parent_numeroControlePNCPAta
        )
        SELECT
            {max_id} + ROW_NUMBER() OVER (ORDER BY parent_numeroControlePNCPAta, numeroItem) AS id,
            numeroItem, descricao, materialOuServico, materialOuServicoNome,
            valorUnitarioEstimado, valorTotal, quantidade, unidadeMedida,
            orcamentoSigiloso, itemCategoriaId, itemCategoriaNome, patrimonio,
            codigoRegistroImobiliario, criterioJulgamentoId, criterioJulgamentoNome,
            situacaoCompraItem, situacaoCompraItemNome, tipoBeneficio, tipoBeneficioNome,
            incentivoProdutivoBasico, dataInclusao, dataAtualizacao, temResultado,
            imagem, aplicabilidadeMargemPreferenciaNormal, aplicabilidadeMargemPreferenciaAdicional,
            percentualMargemPreferenciaNormal, percentualMargemPreferenciaAdicional,
            ncmNbsCodigo, ncmNbsDescricao, catalogo, categoriaItemCatalogo,
            catalogoCodigoItem, informacaoComplementar, tipoMargemPreferencia,
            exigenciaConteudoNacional, parent_cnpj, parent_numeroControlePNCPAta
        FROM `{STAGING_TABLE}`
    """
    print(f"  Inserindo dados na tabela principal com IDs iniciando em {max_id + 1:,}...")
    start = time.time()
    job = client.query(sql)
    job.result()
    elapsed = time.time() - start
    print(f"  INSERT concluído em {elapsed:.1f}s")


def create_test_csv(lines: int = 10) -> str:
    """Cria um arquivo CSV de teste com N linhas do arquivo original."""
    print(f"  Criando arquivo de teste com {lines} linhas...")
    with open(CSV_PATH, "r", encoding="utf-8") as f_in:
        header = f_in.readline()
        data_lines = [f_in.readline() for _ in range(lines)]

    with open(TEST_CSV_PATH, "w", encoding="utf-8") as f_out:
        f_out.write(header)
        f_out.writelines(data_lines)

    print(f"  Arquivo de teste criado: {TEST_CSV_PATH}")
    return TEST_CSV_PATH


def cleanup_test_csv():
    """Remove arquivo de teste temporário."""
    if os.path.exists(TEST_CSV_PATH):
        os.remove(TEST_CSV_PATH)
        print(f"  Arquivo de teste removido.")


def run_test():
    """Executa o teste com 10 linhas para validar a pipeline."""
    print("\n" + "="*60)
    print("FASE 1: TESTE COM 10 LINHAS")
    print("="*60)

    client = get_client()

    # Dados antes do teste
    count_before = get_row_count(client, MAIN_TABLE)
    max_id_before = get_max_id(client)
    print(f"\nEstado atual da tabela principal:")
    print(f"  Total de linhas: {count_before:,}")
    print(f"  Max ID: {max_id_before:,}")

    # Criar arquivo de teste
    test_path = create_test_csv(10)

    try:
        # Criar staging e carregar 10 linhas
        print("\nCriando tabela staging de teste...")
        create_staging_table(client)
        load_csv_to_staging(client, test_path)

        staging_count = get_row_count(client, STAGING_TABLE)
        print(f"  Linhas na staging: {staging_count:,}")

        if staging_count == 0:
            print("ERRO: Staging vazia! Abortando teste.")
            return False

        # Inserir na tabela principal
        insert_staging_into_main(client, max_id_before)

        # Verificar resultado
        count_after = get_row_count(client, MAIN_TABLE)
        new_max_id = get_max_id(client)
        print(f"\nResultado do teste:")
        print(f"  Linhas antes: {count_before:,}")
        print(f"  Linhas após:  {count_after:,}")
        print(f"  Diferença:    {count_after - count_before:,} (esperado: {staging_count})")
        print(f"  Novo Max ID:  {new_max_id:,}")

        # Verificar integridade: linhas originais não foram afetadas
        min_id_check = next(client.query(
            f"SELECT MIN(id) as min_id FROM `{MAIN_TABLE}`"
        ).result())['min_id']

        if count_after == count_before + staging_count and min_id_check == 1:
            print(f"\n✅ TESTE PASSOU: {staging_count} linhas inseridas corretamente, "
                  f"dados originais intactos (min_id={min_id_check}).")

            # Reverter o teste (remover as 10 linhas inseridas)
            print(f"\nRevertendo linhas de teste (removendo IDs > {max_id_before})...")
            client.query(
                f"DELETE FROM `{MAIN_TABLE}` WHERE id > {max_id_before}"
            ).result()
            count_reverted = get_row_count(client, MAIN_TABLE)
            print(f"  Linhas após reversão: {count_reverted:,} (esperado: {count_before:,})")
            if count_reverted == count_before:
                print("  ✅ Reversão bem-sucedida! Dados originais intactos.")
            return True
        else:
            print(f"\n❌ TESTE FALHOU: Verificar dados manualmente.")
            return False

    finally:
        delete_staging_if_exists(client)
        cleanup_test_csv()


def run_full_migration():
    """Executa a migração completa do arquivo de 2026."""
    print("\n" + "="*60)
    print("FASE 2: CARGA COMPLETA — itens_consolidado_2026_padronizado.csv")
    print("="*60)

    client = get_client()

    # Estado antes
    count_before = get_row_count(client, MAIN_TABLE)
    max_id_before = get_max_id(client)
    print(f"\nEstado atual da tabela principal:")
    print(f"  Total de linhas: {count_before:,}")
    print(f"  Max ID atual:    {max_id_before:,}")

    try:
        # Passo 1: Criar staging
        print("\nPasso 1: Criando tabela staging...")
        create_staging_table(client)

        # Passo 2: Carregar CSV na staging
        print("\nPasso 2: Carregando CSV na staging...")
        load_csv_to_staging(client, CSV_PATH)

        staging_count = get_row_count(client, STAGING_TABLE)
        print(f"  Linhas carregadas na staging: {staging_count:,}")

        if staging_count == 0:
            print("ERRO: Staging vazia! Abortando migração.")
            return

        # Passo 3: Inserir na tabela principal
        print(f"\nPasso 3: Inserindo {staging_count:,} linhas na tabela principal...")
        insert_staging_into_main(client, max_id_before)

        # Passo 4: Verificação
        count_after = get_row_count(client, MAIN_TABLE)
        new_max_id = get_max_id(client)

        print(f"\n{'='*60}")
        print("RESULTADO FINAL")
        print(f"{'='*60}")
        print(f"  Linhas antes da migração: {count_before:,}")
        print(f"  Linhas após a migração:   {count_after:,}")
        print(f"  Novas linhas inseridas:   {count_after - count_before:,}")
        print(f"  Linhas no staging:        {staging_count:,}")
        print(f"  Novo Max ID:              {new_max_id:,}")

        if count_after == count_before + staging_count:
            print(f"\n✅ MIGRAÇÃO CONCLUÍDA COM SUCESSO!")
        else:
            diff = count_after - count_before
            print(f"\n⚠️  ATENÇÃO: Esperado {staging_count:,} linhas, "
                  f"mas foram inseridas {diff:,}. Verificar BigQuery manualmente.")

    finally:
        # Passo 5: Limpar staging
        print("\nPasso 5: Removendo tabela staging...")
        delete_staging_if_exists(client)


# ─── Entry Point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    # Carregar .env se existir
    env_path = os.path.join(os.path.dirname(__file__), '.env')
    if os.path.exists(env_path):
        from dotenv import load_dotenv
        load_dotenv(env_path)
        print("Variáveis .env carregadas.")

    if not os.path.exists(CSV_PATH):
        print(f"❌ Arquivo CSV não encontrado: {CSV_PATH}")
        sys.exit(1)

    # Executar teste primeiro
    test_ok = run_test()

    if not test_ok:
        print("\n❌ Teste falhou. Migração completa ABORTADA. Verifique os erros acima.")
        sys.exit(1)

    print("\n✅ Teste passou! Iniciando carga completa em 5 segundos...")
    print("   (Pressione Ctrl+C para cancelar)")
    time.sleep(5)

    run_full_migration()
