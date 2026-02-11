"""
Script para adicionar campo 'id' à tabela itens no BigQuery
"""
from google.cloud import bigquery

PROJECT_ID = 'pncp-466018'
DATASET_ID = 'pncp_data'

def add_id_column_to_itens():
    """Adiciona coluna id à tabela itens usando ROW_NUMBER"""
    client = bigquery.Client(project=PROJECT_ID)
    
    print("Criando nova tabela com campo id...")
    
    # Criar uma nova tabela com id baseado em ROW_NUMBER
    sql = f"""
        CREATE OR REPLACE TABLE `{PROJECT_ID}.{DATASET_ID}.itens_with_id` AS
        SELECT 
            ROW_NUMBER() OVER (ORDER BY parent_numeroControlePNCPAta, numeroItem) as id,
            *
        FROM `{PROJECT_ID}.{DATASET_ID}.itens`
    """
    
    job = client.query(sql)
    job.result()
    
    print("✅ Tabela itens_with_id criada com sucesso!")
    
    # Renomear tabelas
    print("Renomeando tabelas...")
    
    # Backup da tabela original
    sql_backup = f"""
        CREATE OR REPLACE TABLE `{PROJECT_ID}.{DATASET_ID}.itens_backup` AS
        SELECT * FROM `{PROJECT_ID}.{DATASET_ID}.itens`
    """
    job = client.query(sql_backup)
    job.result()
    print("✅ Backup criado: itens_backup")
    
    # Deletar tabela original
    table_id = f"{PROJECT_ID}.{DATASET_ID}.itens"
    client.delete_table(table_id)
    print("✅ Tabela itens deletada")
    
    # Renomear nova tabela
    sql_rename = f"""
        CREATE OR REPLACE TABLE `{PROJECT_ID}.{DATASET_ID}.itens` AS
        SELECT * FROM `{PROJECT_ID}.{DATASET_ID}.itens_with_id`
    """
    job = client.query(sql_rename)
    job.result()
    print("✅ Nova tabela itens criada com campo id")
    
    # Deletar tabela temporária
    temp_table_id = f"{PROJECT_ID}.{DATASET_ID}.itens_with_id"
    client.delete_table(temp_table_id)
    print("✅ Tabela temporária deletada")
    
    # Verificar resultado
    sql_check = f"""
        SELECT COUNT(*) as total, MIN(id) as min_id, MAX(id) as max_id
        FROM `{PROJECT_ID}.{DATASET_ID}.itens`
    """
    job = client.query(sql_check)
    result = next(job.result())
    
    print(f"\n📊 Verificação:")
    print(f"   Total de registros: {result['total']:,}")
    print(f"   ID mínimo: {result['min_id']}")
    print(f"   ID máximo: {result['max_id']}")
    
    print("\n🎉 Processo concluído com sucesso!")
    print("   Tabela 'itens' agora possui o campo 'id'")
    print("   Backup disponível em 'itens_backup'")

if __name__ == "__main__":
    add_id_column_to_itens()
