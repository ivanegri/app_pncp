"""
Script para migrar a tabela resultados do PostgreSQL para o BigQuery
"""
import os
import sys
import pandas as pd
from google.cloud import bigquery
from sqlalchemy import create_engine, text

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from app.config import Config

# Configurações
DATABASE_URL = Config.SQLALCHEMY_DATABASE_URI
GCP_PROJECT_ID = Config.GCP_PROJECT_ID
GCP_DATASET_ID = Config.GCP_DATASET_ID

BATCH_SIZE = 10000  # Tamanho do lote para migração

def create_bigquery_table():
    """Cria a tabela resultados no BigQuery"""
    client = bigquery.Client(project=GCP_PROJECT_ID)
    
    schema = [
        bigquery.SchemaField("numeroControlePNCPCompra", "STRING"),
        bigquery.SchemaField("numeroItem", "INTEGER"),
        bigquery.SchemaField("sequencialResultado", "INTEGER"),
        bigquery.SchemaField("niFornecedor", "STRING"),
        bigquery.SchemaField("nomeRazaoSocialFornecedor", "STRING"),
        bigquery.SchemaField("tipoPessoa", "STRING"),
        bigquery.SchemaField("porteFornecedorId", "INTEGER"),
        bigquery.SchemaField("porteFornecedorNome", "STRING"),
        bigquery.SchemaField("valorUnitarioHomologado", "FLOAT"),
        bigquery.SchemaField("quantidadeHomologada", "FLOAT"),
        bigquery.SchemaField("valorTotalHomologado", "FLOAT"),
        bigquery.SchemaField("percentualDesconto", "FLOAT"),
        bigquery.SchemaField("situacaoCompraItemResultadoId", "INTEGER"),
        bigquery.SchemaField("situacaoCompraItemResultadoNome", "STRING"),
        bigquery.SchemaField("dataResultado", "DATE"),
        bigquery.SchemaField("dataInclusao", "TIMESTAMP"),
        bigquery.SchemaField("dataAtualizacao", "TIMESTAMP"),
        bigquery.SchemaField("ordemClassificacaoSrp", "INTEGER"),
        bigquery.SchemaField("indicadorSubcontratacao", "BOOLEAN"),
        bigquery.SchemaField("aplicacaoMargemPreferencia", "BOOLEAN"),
        bigquery.SchemaField("aplicacaoBeneficioMeEpp", "BOOLEAN"),
        bigquery.SchemaField("aplicacaoCriterioDesempate", "BOOLEAN"),
        bigquery.SchemaField("motivoCancelamento", "STRING"),
        bigquery.SchemaField("dataCancelamento", "TIMESTAMP"),
        bigquery.SchemaField("codigoPais", "STRING"),
        bigquery.SchemaField("paisOrigemProdutoServico", "STRING"),
        bigquery.SchemaField("naturezaJuridicaId", "INTEGER"),
        bigquery.SchemaField("naturezaJuridicaNome", "STRING"),
        bigquery.SchemaField("amparoLegalMargemPreferencia", "STRING"),
        bigquery.SchemaField("amparoLegalCriterioDesempate", "STRING"),
        bigquery.SchemaField("moedaEstrangeira", "STRING"),
        bigquery.SchemaField("valorNominalMoedaEstrangeira", "FLOAT"),
        bigquery.SchemaField("dataCotacaoMoedaEstrangeira", "DATE"),
        bigquery.SchemaField("timezoneCotacaoMoedaEstrangeira", "STRING"),
    ]
    
    table_id = f"{GCP_PROJECT_ID}.{GCP_DATASET_ID}.resultados"
    table = bigquery.Table(table_id, schema=schema)
    
    # Criar ou substituir tabela
    table = client.create_table(table, exists_ok=True)
    print(f"✅ Tabela {table_id} criada/verificada no BigQuery")
    
    return table_id

def migrate_resultados_to_bigquery():
    """Migra dados da tabela resultados do PostgreSQL para BigQuery em lotes"""
    engine = create_engine(DATABASE_URL)
    client = bigquery.Client(project=GCP_PROJECT_ID)
    
    # Criar tabela no BigQuery
    table_id = create_bigquery_table()
    
    # Contar total de registros
    with engine.connect() as conn:
        result = conn.execute(text("SELECT COUNT(*) FROM resultados"))
        total_rows = result.scalar()
    
    print(f"📊 Total de registros a migrar: {total_rows:,}")
    
    if total_rows == 0:
        print("⚠️  Nenhum registro para migrar!")
        return
    
    # Migrar em lotes
    offset = 0
    total_migrated = 0
    
    while offset < total_rows:
        print(f"\n🔄 Migrando lote {offset:,} a {min(offset + BATCH_SIZE, total_rows):,}...")
        
        # Buscar lote do PostgreSQL
        query = text(f"""
            SELECT 
                "numeroControlePNCPCompra",
                "numeroItem",
                "sequencialResultado",
                "niFornecedor",
                "nomeRazaoSocialFornecedor",
                "tipoPessoa",
                "porteFornecedorId",
                "porteFornecedorNome",
                "valorUnitarioHomologado",
                "quantidadeHomologada",
                "valorTotalHomologado",
                "percentualDesconto",
                "situacaoCompraItemResultadoId",
                "situacaoCompraItemResultadoNome",
                "dataResultado",
                "dataInclusao",
                "dataAtualizacao",
                "ordemClassificacaoSrp",
                "indicadorSubcontratacao",
                "aplicacaoMargemPreferencia",
                "aplicacaoBeneficioMeEpp",
                "aplicacaoCriterioDesempate",
                "motivoCancelamento",
                "dataCancelamento",
                "codigoPais",
                "paisOrigemProdutoServico",
                "naturezaJuridicaId",
                "naturezaJuridicaNome",
                "amparoLegalMargemPreferencia",
                "amparoLegalCriterioDesempate",
                "moedaEstrangeira",
                "valorNominalMoedaEstrangeira",
                "dataCotacaoMoedaEstrangeira",
                "timezoneCotacaoMoedaEstrangeira"
            FROM resultados
            ORDER BY id
            LIMIT :limit OFFSET :offset
        """)
        
        df = pd.read_sql(query, engine, params={"limit": BATCH_SIZE, "offset": offset})
        
        if df.empty:
            break
        
        # Converter tipos de dados para BigQuery
        # Remover timezone de timestamps
        for col in df.select_dtypes(include=['datetime', 'datetimetz']).columns:
            if df[col].dt.tz is not None:
                df[col] = df[col].dt.tz_localize(None)
        
        # Upload para BigQuery
        job_config = bigquery.LoadJobConfig(
            write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
        )
        
        job = client.load_table_from_dataframe(
            df, table_id, job_config=job_config
        )
        job.result()  # Aguardar conclusão
        
        total_migrated += len(df)
        offset += BATCH_SIZE
        
        print(f"✅ Lote migrado: {len(df)} registros")
        print(f"📊 Total migrado: {total_migrated:,} / {total_rows:,} ({100*total_migrated/total_rows:.1f}%)")
    
    print(f"\n🎉 Migração concluída! Total de {total_migrated:,} registros migrados para BigQuery")

if __name__ == "__main__":
    migrate_resultados_to_bigquery()
