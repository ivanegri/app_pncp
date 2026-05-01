import os
import pandas as pd
from google.cloud import bigquery
from google.api_core.exceptions import Conflict

# Configuration
import os
PROJECT_ID = os.environ.get('GCP_PROJECT_ID', 'pncp-466018')
DATASET_ID = 'pncp_data'
CSV_DIR = 'CSVs'

# File mappings: Table Name -> List of Files
FILES_TO_MIGRATE = {
    #'atas': [
    #     'atas_2026_full.csv',]
    #     'atas_2025_full.csv'
    # ],
    #'itens': [
    #     'itens_consolidado_2024_padronizado.csv',
    #     'itens_consolidado_2025_padronizado.csv'
    'users': [
         'users.csv'
    ],
    #'orgaos': [
    #   'orgaos_full_regiao.csv'
    #]
    #'compras_futuras':[
    #    'compras_2026_abertas_processed.csv'
    #]
    'resultados':[
        'resultados_2.csv'
    ]
}

CHUNK_SIZE = 50000  # Adjust based on memory

def create_dataset_if_not_exists(client: bigquery.Client, dataset_id: str):
    dataset_ref = f"{client.project}.{dataset_id}"
    try:
        client.get_dataset(dataset_ref)
        print(f"Dataset {dataset_ref} already exists.")
    except Exception:
        print(f"Creating dataset {dataset_ref}...")
        dataset = bigquery.Dataset(dataset_ref)
        dataset.location = "US" # Or standard location
        client.create_dataset(dataset, timeout=30)
        print(f"Dataset {dataset_ref} created.")

def upload_csv_to_bigquery(client: bigquery.Client, table_name: str, file_path: str, autodetect: bool = True):
    table_id = f"{PROJECT_ID}.{DATASET_ID}.{table_name}"
    
    print(f"Processing {file_path} for table {table_id}...")
    
    job_config = bigquery.LoadJobConfig(
        source_format=bigquery.SourceFormat.CSV,
        skip_leading_rows=1,
        autodetect=autodetect, # Use parameter
        write_disposition=bigquery.WriteDisposition.WRITE_APPEND, # Append for multiple files
        allow_quoted_newlines=True
    )
    
    # We will upload the file directly using load_table_from_file which is efficient for CSVs
    # However, to ensure schemas match across files if we append, we rely on BigQuery's schema evolution
    # or consistent CSV headers.
    
    with open(file_path, "rb") as source_file:
        job = client.load_table_from_file(source_file, table_id, job_config=job_config)

    print(f"Job {job.job_id} started...")
    
    try:
        job.result()  # Waits for the job to complete.
        print(f"Loaded {job.output_rows} rows from {file_path} into {table_id}.")
    except Exception as e:
        print(f"Error loading {file_path}: {e}")
        if hasattr(e, 'errors'):
            print("Detailed errors:")
            for error in e.errors:
                print(error)

def main():
    print(f"Authenticating with Project ID: {PROJECT_ID}...")
    # Client will use Application Default Credentials from `gcloud auth application-default login`
    client = bigquery.Client(project=PROJECT_ID)
    
    create_dataset_if_not_exists(client, DATASET_ID)
    
    for table, files in FILES_TO_MIGRATE.items():
        print(f"\n--- Migrating table: {table} ---")
        
        # Optional: Truncate table before starting if you want a fresh start
        # Uncomment below if you want to wipe the table first (be careful!)
        # table_id = f"{PROJECT_ID}.{DATASET_ID}.{table}"
        # try:
        #     client.delete_table(table_id, not_found_ok=True)
        #     print(f"Table {table_id} deleted for fresh load.")
        # except Exception as e:
        #     print(f"Error deleting table: {e}")

        for filename in files:
            file_path = os.path.join(CSV_DIR, filename)
            if os.path.exists(file_path):
                # Disable autodetect for 'itens' to avoid schema conflicts on append
                # Enable for others (users, orgaos)
                #do_autodetect = False if table == 'itens' else True
                upload_csv_to_bigquery(client, table, file_path, autodetect=False)
            else:
                print(f"File not found: {file_path}")

if __name__ == "__main__":
    main()
