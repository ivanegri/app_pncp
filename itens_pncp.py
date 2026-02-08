import pandas as pd
import requests
import os
import sys
import time

# Configuration
INPUT_CSV = "./CSVs/compras_2024_unificadas.csv"
OUTPUT_DIR = "./data"
OUTPUT_CSV = os.path.join(OUTPUT_DIR, "itens_consolidado.csv")
LOG_FILE = os.path.join(OUTPUT_DIR, "itens_processados.txt")

# Ensure output directory exists
os.makedirs(OUTPUT_DIR, exist_ok=True)

# 1. Load Processed IDs to allow resuming
# We will use 'numeroControlePNCPAta' as the unique key for tracking progress
processed_ids = set()
if os.path.exists(LOG_FILE):
    with open(LOG_FILE, "r") as f:
        processed_ids = set(line.strip() for line in f if line.strip())
    print(f"Resuming... {len(processed_ids)} records already processed.")

# 2. Load Input Data
print("Loading input CSV...")
# Read specific columns to save memory and ensure text validity
df = pd.read_csv(INPUT_CSV, dtype=str, usecols=['cnpjOrgao', 'numeroControlePNCPAta'])
total_records = len(df)
print(f"Total records to process: {total_records}")

api_url_template = "https://pncp.gov.br/api/pncp/v1/orgaos/{cnpj}/compras/{ano}/{sequencial}/itens"
found_count = 0

# Open log file in append mode
with open(LOG_FILE, "a") as log_f:
    for index, row in df.iterrows():
        ata_id = str(row['numeroControlePNCPAta']).strip()
        
        # Skip if already processed
        if ata_id in processed_ids:
            continue
            
        cnpj = str(row['cnpjOrgao']).strip()
        
        # Parse 'numeroControlePNCPAta' -> CNPJ-R-SEQ/ANO-ATA
        # Pattern: "12345678000199-1-000001/2024-000001"
        try:
            # Split by '/' first: ["...SEQ", "ANO-..."]
            parts_slash = ata_id.split('/')
            if len(parts_slash) != 2:
                raise ValueError("Invalid format (missing /)")
            
            part_left = parts_slash[0] # CNPJ-R-SEQ
            part_right = parts_slash[1] # ANO-ATA
            
            # Extract Sequencial (last part of left side)
            sequencial = part_left.split('-')[-1]
            
            # Extract Ano (first part of right side)
            ano = part_right.split('-')[0]
            
        except Exception as e:
            print(f"[{index+1}/{total_records}] Error parsing ID {ata_id}: {e}")
            log_f.write(f"{ata_id}\n") # Skip malformed but mark as processed to avoid retry loop
            log_f.flush()
            continue

        print(f"[{index+1}/{total_records}] Fetching items for {ata_id} (Seq: {sequencial}, Ano: {ano})...", end="\r")

        all_items = []
        page = 1
        page_size = 50 
        
        try:
            while True:
                url = api_url_template.format(cnpj=cnpj, ano=ano, sequencial=sequencial)
                params = {"pagina": page, "tamanhoPagina": page_size}
                
                response = requests.get(url, params=params, timeout=15)
                
                if response.status_code == 200:
                    data = response.json()
                    # Items are usually directly in the list
                    # Or sometimes API structure implies we just check if it's a list
                    if isinstance(data, list) and data:
                        all_items.extend(data)
                        if len(data) < page_size:
                            break # Last page
                        page += 1
                    else:
                        break # Empty
                elif response.status_code == 404:
                    break # Not found
                else:
                    # Temporary error?
                    break 
            
            if all_items:
                found_count += len(all_items)
                df_items = pd.DataFrame(all_items)
                
                # Add context columns
                df_items['parent_cnpj'] = cnpj
                df_items['parent_numeroControlePNCPAta'] = ata_id
                
                # Save to consolidated CSV
                write_header = not os.path.exists(OUTPUT_CSV)
                df_items.to_csv(OUTPUT_CSV, mode='a', header=write_header, index=False)
                
                # Optional: Print success occasionally
                # print(f"  -> Found {len(all_items)} items.")

            # Mark as processed
            log_f.write(f"{ata_id}\n")
            log_f.flush()

        except KeyboardInterrupt:
            print("\nScript interrupted by user. Exiting...")
            sys.exit(0)
        except Exception as e:
            print(f"\nError fetching items for {ata_id}: {e}")
            # Do not mark as processed if network error, so we can retry? 
            # Or mark to avoid block? Let's check: users usually prefer to retry later.
            continue
            
print(f"\nDone. Total items found: {found_count}")