
from sqlalchemy import create_engine, text
import os
import time

# Database connection details
DB_USER = os.environ.get('DB_USER', 'admin')
DB_PASS = os.environ.get('DB_PASS', 'admin123')
DB_HOST = os.environ.get('DB_HOST', '216.22.5.204')
DB_PORT = os.environ.get('DB_PORT', '5432')
DB_NAME = os.environ.get('DB_NAME', 'jupiter')

DATABASE_URI = f'postgresql://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}'

def fix_search_index():
    print(f"Connecting to {DB_HOST}...")
    engine = create_engine(DATABASE_URI)
    
    with engine.connect() as conn:
        print("Connected.")
        
        # 1. Check if column exists
        print("Checking 'busca_descricao_idx' column on 'itens'...")
        check_col = conn.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name='itens' AND column_name='busca_descricao_idx'"))
        
        if not check_col.fetchone():
            print("Column 'busca_descricao_idx' MISSING. Creating it...")
            conn.execute(text("ALTER TABLE itens ADD COLUMN busca_descricao_idx tsvector"))
            conn.commit()
            print("Column created.")
        else:
            print("Column 'busca_descricao_idx' EXISTS.")
            
        # 2. Populate column (Update NULLs)
        print("Checking for unindexed rows...")
        
        # Get count of nulls
        null_count = conn.execute(text("SELECT count(*) FROM itens WHERE busca_descricao_idx IS NULL")).scalar()
        print(f"Found {null_count} rows with NULL index.")
        
        if null_count > 0:
            print("Populating index (this may take a while)...")
            start_time = time.time()
            
            # Using standard update for tsvector
            # "portuguese" configuration is used as per app/routes.py
            result = conn.execute(text("""
                UPDATE itens 
                SET busca_descricao_idx = to_tsvector('portuguese', COALESCE(descricao, '')) 
                WHERE busca_descricao_idx IS NULL
            """))
            conn.commit()
            
            end_time = time.time()
            print(f"Updated {result.rowcount} rows in {end_time - start_time:.2f} seconds.")
        else:
            print("All rows appear to be indexed.")

        # 3. Create Index if not exists
        print("Checking/Creating GIN index...")
        # Check if index exists is harder in SQL agnostic way, but we can try creating it with IF NOT EXISTS if PG supports it, 
        # or catch exception. PG supports IF NOT EXISTS for indexes in newer versions, or we check pg_indexes.
        
        check_idx = conn.execute(text("SELECT indexname FROM pg_indexes WHERE tablename = 'itens' AND indexname = 'idx_itens_busca_descricao'"))
        if not check_idx.fetchone():
            print("Creating GIN index 'idx_itens_busca_descricao'...")
            try:
                conn.execute(text("CREATE INDEX idx_itens_busca_descricao ON itens USING GIN(busca_descricao_idx)"))
                conn.commit()
                print("Index created.")
            except Exception as e:
                print(f"Error creating index (might already exist): {e}")
        else:
            print("Index 'idx_itens_busca_descricao' already exists.")

        print("Done.")

if __name__ == "__main__":
    try:
        fix_search_index()
    except Exception as e:
        print(f"An error occurred: {e}")
