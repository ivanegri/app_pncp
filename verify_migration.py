import pandas as pd
from sqlalchemy import create_engine, text
import sys

# Database connection details
DB_USER = 'admin'
DB_PASS = 'admin123'
DB_HOST = '216.22.5.204'
DB_PORT = '5432'
DB_NAME = 'jupiter'
DATABASE_URI = f'postgresql://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}'

EXPECTED_COUNTS = {
    'atas': 1159650,
    'orgaos': 59080,
    'itens': 2522385 # Count from pandas read
}

def verify():
    print("Verifying migration...")
    try:
        engine = create_engine(DATABASE_URI)
        with engine.connect() as conn:
            all_passed = True
            for table, expected in EXPECTED_COUNTS.items():
                try:
                    res = conn.execute(text(f"SELECT count(*) FROM {table}"))
                    count = res.fetchone()[0]
                    print(f"Table '{table}': {count} rows (Expected ~{expected})")
                    
                    if abs(count - expected) > 1000: # Allow small difference due to header/parsing
                        print(f"WARNING: Count mismatch for '{table}'!")
                        all_passed = False
                    else:
                        print(f"SUCCESS: '{table}' count looks correct.")
                except Exception as e:
                    print(f"ERROR querying '{table}': {e}")
                    all_passed = False
            
            if all_passed:
                print("\nMigration Verified Successfully!")
            else:
                print("\nMigration Verification Failed or Incomplete.")
    
    except Exception as e:
        print(f"Connection error: {e}")

if __name__ == "__main__":
    verify()
