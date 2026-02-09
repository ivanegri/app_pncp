
from sqlalchemy import create_engine, text
import os

DB_USER = os.environ.get('DB_USER', 'admin')
DB_PASS = os.environ.get('DB_PASS', 'admin123')
DB_HOST = os.environ.get('DB_HOST', '216.22.5.204')
DB_PORT = os.environ.get('DB_PORT', '5432')
DB_NAME = os.environ.get('DB_NAME', 'jupiter')

DATABASE_URI = f'postgresql://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}'

engine = create_engine(DATABASE_URI)

with engine.connect() as conn:
    print("Checking if 'busca_descricao_idx' column exists in 'itens'...")
    try:
        # Check column existence
        result = conn.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name='itens' AND column_name='busca_descricao_idx'"))
        if result.fetchone():
            print("Column 'busca_descricao_idx' FOUND.")
            
            # Check if it has data
            print("Checking for NULL values...")
            total = conn.execute(text("SELECT count(*) FROM itens")).scalar()
            nulls = conn.execute(text("SELECT count(*) FROM itens WHERE busca_descricao_idx IS NULL")).scalar()
            
            print(f"Total rows: {total}")
            print(f"Rows with NULL busca_descricao_idx: {nulls}")
            
            if total > 0 and (total - nulls) > 0:
                print("Sample value:")
                sample = conn.execute(text("SELECT busca_descricao_idx FROM itens WHERE busca_descricao_idx IS NOT NULL LIMIT 1")).scalar()
                print(sample)
            else:
                print("Column appears to be empty/NULL.")
                
        else:
            print("Column 'busca_descricao_idx' NOT FOUND.")
            
    except Exception as e:
        print(f"Error: {e}")
