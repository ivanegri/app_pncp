
from app import create_app, db
from sqlalchemy import text
import requests
import json

app = create_app()

def debug_item(item_id):
    with app.app_context():
        print(f"--- Debugging Item ID: {item_id} ---")
        
        # 1. Force reflection to ensure classes are available
        from app.models import Base
        Base.prepare(db.engine, reflect=True)
        
        Itens = Base.classes.itens
        Atas = Base.classes.atas
        
        item = db.session.query(Itens).get(item_id)
        if not item:
            print("Item NOT FOUND in DB.")
            return

        print(f"Item Desc: {item.descricao}")
        print(f"Item Numero: {item.numeroItem}")
        print(f"Item Parent CNPJ: {item.parent_cnpj}")
        print(f"Item Parent Ata Control: {item.parent_numeroControlePNCPAta}")
        
        ata = None
        if item.parent_numeroControlePNCPAta:
            ata = db.session.query(Atas).filter_by(numeroControlePNCPAta=item.parent_numeroControlePNCPAta).first()
            
        if not ata:
            print("Ata NOT FOUND.")
            return
            
        print(f"Ata Found: ID {ata.id}")
        print(f"Ata Numero Controle Compra: {ata.numeroControlePNCPCompra}")
        
        if not ata.numeroControlePNCPCompra:
            print("Ata misses numeroControlePNCPCompra. Cannot build URL.")
            return
            
        # Simulate URL Construction
        ctrl = ata.numeroControlePNCPCompra
        cnpj = ctrl[:14]
        parts = ctrl.split('/')
        
        if len(parts) == 2:
            ano = parts[1][:4]
            sequencial = parts[0][-6:]
            
            print(f"Extracted -> CNPJ: {cnpj}, Ano: {ano}, Sequencial: {sequencial}")
            
            # 1. Try Original URL (Results List)
            url_list = f"https://pncp.gov.br/api/pncp/v1/orgaos/{cnpj}/compras/{ano}/{sequencial}/itens/{item.numeroItem}/resultados"
            print(f"\nRequesting LIST URL: {url_list}")
            try:
                resp = requests.get(url_list, timeout=10)
                print(f"Status: {resp.status_code}")
                if resp.status_code == 200:
                    data = resp.json()
                    print(f"Response (First 500 chars): {json.dumps(data)[:500]}")
                    if isinstance(data, list) and len(data) > 0:
                        print(f"Result count: {len(data)}")
                        print(f"First item keys: {list(data[0].keys())}")
                        print(f"First item content: {json.dumps(data[0], indent=2)}")
                    else:
                        print("Response is not a list or is empty.")
                else:
                    print(f"Error: {resp.text}")
            except Exception as e:
                print(f"Request Error: {e}")

            # 2. Try User's URL (Specific Result /1)
            url_user = f"https://pncp.gov.br/api/pncp/v1/orgaos/{cnpj}/compras/{ano}/{sequencial}/itens/{item.numeroItem}/resultados/1"
            print(f"\nRequesting USER URL: {url_user}")
            try:
                resp = requests.get(url_user, timeout=10)
                print(f"Status: {resp.status_code}")
                if resp.status_code == 200:
                    data = resp.json()
                    print(f"Response: {json.dumps(data)[:500]}")
                else:
                    print(f"Error: {resp.text}")
            except Exception as e:
                print(f"Request Error: {e}")

        else:
            print("Invalid Control Number format.")

if __name__ == "__main__":
    # ID from screenshot URL: 5441804
    # If that doesn't exist, I'll search for one with item number 49 and the cnpj
    debug_item(5441804) 
