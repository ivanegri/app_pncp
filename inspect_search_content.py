
from sqlalchemy import create_engine, text
import os

# Database connection details
DB_USER = os.environ.get('DB_USER', 'admin')
DB_PASS = os.environ.get('DB_PASS', 'admin123')
DB_HOST = os.environ.get('DB_HOST', '216.22.5.204')
DB_PORT = os.environ.get('DB_PORT', '5432')
DB_NAME = os.environ.get('DB_NAME', 'jupiter')

DATABASE_URI = f'postgresql://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}'

def inspect_content():
    print(f"Connecting to {DB_HOST}...")
    engine = create_engine(DATABASE_URI)
    
    with engine.connect() as conn:
        print("Connected.")
        
        # 1. Check raw content of the new column
        print("\n--- Sample Data (busca_descricao_idx) ---")
        sql = text("SELECT id, descricao, busca_descricao_idx FROM itens LIMIT 5")
        results = conn.execute(sql).fetchall()
        
        for row in results:
            print(f"ID: {row[0]}")
            print(f"Desc: {row[1]}")
            print(f"Vector: {row[2]}")
            print("-" * 30)

        # 2. Try a raw search query similar to the app
        term = "papel" # Common term
        print(f"\n--- Testing Search for '{term}' ---")
        
        # Using websearch_to_tsquery as in the app
        sql_search = text(f"SELECT count(*) FROM itens WHERE busca_descricao_idx @@ websearch_to_tsquery('portuguese', '{term}')")
        count = conn.execute(sql_search).scalar()
        print(f"Raw SQL Count for '{term}': {count}")
        
        # 3. Try plain to_tsquery just in case
        sql_plain = text(f"SELECT count(*) FROM itens WHERE busca_descricao_idx @@ to_tsquery('portuguese', '{term}')")
        count_plain = conn.execute(sql_plain).scalar()
        print(f"Plain to_tsquery Count for '{term}': {count_plain}")

if __name__ == "__main__":
    try:
        inspect_content()
    except Exception as e:
        print(f"An error occurred: {e}")
