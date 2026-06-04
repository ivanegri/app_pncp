import requests
import pandas as pd
import os

# Ensure the output directory exists
os.makedirs("data/atas", exist_ok=True)

url = "https://pncp.gov.br/api/consulta/v1/atas"
page = 1
total_pages = None

while True:
    try:
        params = {
            'dataInicial': '20260101',
            'dataFinal': '20261231',
            "pagina": page,
            'tamanhoPagina': 50,  
        }
        
        print(f"Fetching page {page}...", end="")
        response = requests.get(url, params=params)

        if response.status_code == 200:
            result = response.json()
            
            # The API returns a dictionary with 'data' containing the list and metadata like 'totalPaginas'
            records = result.get('data', [])
            if total_pages is None:
                total_pages = result.get('totalPaginas', 0)
                print(f" Total pages to fetch: {total_pages}")
            else:
                print(" Done.")

            if not records:
                print("No more records found.")
                break

            # Save the current page
            pd.DataFrame(records).to_csv(f"data/atas/atas_{page}.csv", index=False)
            
            # Check for end of pagination
            if page >= total_pages:
                print("Reached the last available page.")
                break
            
            page += 1
        else:
            print(f"\nError: {response.status_code}")
            continue

    except Exception as e:
        print(f"\nAn exception occurred: {e}")
        break



