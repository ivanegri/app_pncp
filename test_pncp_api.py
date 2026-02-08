import requests
import pandas as pd
while True:
    try:
        for i in range(1, 100000):
            url = "https://pncp.gov.br/api/pncp/v1/orgaos/"
            params = {
                "razaoSocial": "munic",
                "pagina": i,
                'tamanhoPagina': 50,  
            }
            response = requests.get(url, params=params)

            if response.status_code == 200:
                data = response.json()
                pd.DataFrame(data).to_csv(f"data/orgaos_{params['razaoSocial']}_{params['pagina']}.csv", index=False)
                print(data[0])
            else:
                print(f"Erro: {response.status_code}")
    except Exception as e:
        print(e)
        break



