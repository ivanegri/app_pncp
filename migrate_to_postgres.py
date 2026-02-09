import pandas as pd
from sqlalchemy import create_engine
import os

# Database connection details
DB_USER = 'admin'
DB_PASS = 'admin123'
DB_HOST = '216.22.5.204'
DB_PORT = '5432'
DB_NAME = 'jupiter'

# Connection string
DATABASE_URI = f'postgresql://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}'

def migrate_data():
    print("Connecting to database...")
    try:
        engine = create_engine(DATABASE_URI)
        connection = engine.connect()
        print("Connection successful!")
        connection.close()
    except Exception as e:
        print(f"Error connecting to database: {e}")
        return

    # files_atas = [
    #     'CSVs/atas_2024_full.csv',
    #     'CSVs/atas_2025_full.csv'
    # ]
    # file_orgaos = 'CSVs/orgaos_full.csv'
    # Fixed path for itens
    file_itens =  'data/itens/itens_consolidado_2025_padronizado.csv'

    # 1. Process ATAS (Skipping as it's done)
    # print("\nProcessing ATAS table...")
    # try:
    #     dfs = []
    #     for f in files_atas:
    #         if os.path.exists(f):
    #             print(f"Reading {f}...")
    #             # Read all columns as string first to avoid type inference errors on mixed types, 
    #             # or rely on pandas inference. Using 'dtype=str' or low_memory=False is safer for initial dump.
    #             # However, for dates and numbers, better to let pandas infer or parse dates.
    #             # Let's try default inference first, but keep iterating simple.
    #             df = pd.read_csv(f, low_memory=False) 
    #             dfs.append(df)
    #         else:
    #             print(f"Warning: File {f} not found.")
        
    #     if dfs:
    #         combined_atas = pd.concat(dfs, ignore_index=True)
    #         print(f"Uploading {len(combined_atas)} rows to 'atas' table...")
    #         combined_atas.to_sql('atas', engine, if_exists='replace', index=False, chunksize=1000)
    #         print("ATAS upload complete.")
    #     else:
    #         print("No ATAS files found to upload.")

    # except Exception as e:
    #     print(f"Error processing ATAS: {e}")

    # 2. Process ORGAOS (Skipping as it's done)
    # print("\nProcessing ORGAOS table...")
    # try:
    #     if os.path.exists(file_orgaos):
    #         print(f"Reading {file_orgaos}...")
    #         df_orgaos = pd.read_csv(file_orgaos, low_memory=False)
    #         print(f"Uploading {len(df_orgaos)} rows to 'orgaos' table...")
    #         df_orgaos.to_sql('orgaos', engine, if_exists='replace', index=False, chunksize=1000)
    #         print("ORGAOS upload complete.")
    #     else:
    #         print(f"Warning: File {file_orgaos} not found.")

    # except Exception as e:
    #     print(f"Error processing ORGAOS: {e}")

    # 3. Process ITENS
    print("\nProcessing ITENS table...")
    try:
        itens_files = [
            'data/itens/itens_consolidado_2024_padronizado.csv',
            'data/itens/itens_consolidado_2025_padronizado.csv'
        ]
        
        dfs = []
        for f in itens_files:
            if os.path.exists(f):
                print(f"Reading {f}...")
                df = pd.read_csv(f, low_memory=False)
                dfs.append(df)
            else:
                print(f"Warning: File {f} not found.")

        if dfs:
            print("Concatenating files...")
            combined_itens = pd.concat(dfs, ignore_index=True)
            
            initial_count = len(combined_itens)
            print(f"Total rows before deduplication: {initial_count}")
            
            print("Removing exact duplicates...")
            combined_itens.drop_duplicates(inplace=True)
            
            final_count = len(combined_itens)
            print(f"Total rows after deduplication: {final_count}")
            print(f"Removed {initial_count - final_count} duplicates.")

            print(f"Uploading {final_count} rows to 'itens' table...")
            # Use 'replace' to ensure we have a clean state with the full dataset
            combined_itens.to_sql('itens', engine, if_exists='replace', index=False, chunksize=1000)
            print("ITENS upload complete.")
        else:
            print("No ITENS files found.")

    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"Error processing ITENS: {e}")

if __name__ == "__main__":
    migrate_data()
