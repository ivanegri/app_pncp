import pandas as pd
from sqlalchemy import create_engine, text
import time

# Database connection details
DB_USER = 'admin'
DB_PASS = 'admin123'
DB_HOST = '216.22.5.204'
DB_PORT = '5432'
DB_NAME = 'jupiter'
DATABASE_URI = f'postgresql://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}'

def check_counts():
    try:
        engine = create_engine(DATABASE_URI)
        with engine.connect() as conn:
            # Check atas
            try:
                res = conn.execute(text("SELECT count(*) FROM atas"))
                count = res.fetchone()[0]
                print(f"Current rows in 'atas': {count}")
            except Exception as e:
                print(f"Could not query 'atas': {e}")
            
            # Check orgaos
            try:
                res = conn.execute(text("SELECT count(*) FROM orgaos"))
                count = res.fetchone()[0]
                print(f"Current rows in 'orgaos': {count}")
            except Exception as e:
                pass

            # Check itens
            try:
                res = conn.execute(text("SELECT count(*) FROM itens"))
                count = res.fetchone()[0]
                print(f"Current rows in 'itens': {count}")
            except Exception as e:
                pass
                
    except Exception as e:
        print(f"Connection error: {e}")

if __name__ == "__main__":
    check_counts()
