import pandas as pd
import requests
import os
import sys

# Configuration
INPUT_CSV = "./CSVs/orgaos_full.csv"
OUTPUT_DIR = "./data"
OUTPUT_CSV = os.path.join(OUTPUT_DIR, "unidades_consolidado.csv")
LOG_FILE = os.path.join(OUTPUT_DIR, "cnpjs_processados.txt")

# Ensure output directory exists
os.makedirs(OUTPUT_DIR, exist_ok=True)

# 1. Load Processed CNPJs to allow resuming
processed_cnpjs = set()
if os.path.exists(LOG_FILE):
    with open(LOG_FILE, "r") as f:
        processed_cnpjs = set(line.strip() for line in f if line.strip())
    print(f"Resuming... {len(processed_cnpjs)} CNPJs already processed.")

# 2. Load Input Data
# Use dtype=str to preserve CNPJ leading zeros and avoid DtypeWarnings
print("Loading input CSV...")
df = pd.read_csv(INPUT_CSV, dtype=str, usecols=['cnpj', 'razaoSocial']) 
total_cnpjs = len(df)
print(f"Total CNPJs in file: {total_cnpjs}")

api_url = "https://pncp.gov.br/api/pncp/v1/orgaos/{cnpj}/unidades"
found_count = 0

# Open log file in append mode
with open(LOG_FILE, "a") as log_f:
    for index, row in df.iterrows():
        cnpj = str(row['cnpj']).strip()
        razao_social = row['razaoSocial']
        
        # Skip if already processed
        if cnpj in processed_cnpjs:
            continue
            
        print(f"[{index+1}/{total_cnpjs}] Checking {cnpj} ({razao_social})...", end="\r")
        
        all_units = []
        page = 1
        page_size = 50
        
        try:
            while True:
                params = {"pagina": page, "tamanhoPagina": page_size}
                response = requests.get(api_url.format(cnpj=cnpj), params=params, timeout=10)
                
                if response.status_code == 200:
                    data = response.json()
                    if isinstance(data, list) and data:
                        all_units.extend(data)
                        if len(data) < page_size:
                            break # Last page
                        page += 1
                    else:
                        break # Empty list or unexpected format
                elif response.status_code == 404:
                    break # No units
                else:
                    break # Other error
            
            # Save results if units found
            if all_units:
                found_count += 1
                # Convert to DataFrame
                df_units = pd.DataFrame(all_units)
                # Add parent CNPJ info for context
                df_units['orgao_cnpj'] = cnpj
                df_units['orgao_razao_social'] = razao_social
                
                # Append to consolidated CSV
                # Write header only if file doesn't exist
                write_header = not os.path.exists(OUTPUT_CSV)
                df_units.to_csv(OUTPUT_CSV, mode='a', header=write_header, index=False)
                
                print(f"[{index+1}/{total_cnpjs}] SUCCESS: {cnpj} - {len(all_units)} units found. (Total found: {found_count})")
            else:
                 # Optional: print only every N lines to reduce noise, or just overwrite current line
                 pass

            # Mark as processed
            log_f.write(f"{cnpj}\n")
            log_f.flush() # Ensure written to disk immediately
            
        except KeyboardInterrupt:
            print("\nScript interrupted by user. Exiting...")
            sys.exit(0)
        except Exception as e:
            print(f"\nError processing {cnpj}: {e}")
            # Log it anyway to prevent infinite stuck loop, or you could choose to NOT log it to retry later
            # For now, let's assume we want to retry on errors, so we DON'T write to log_f here
            continue


    
