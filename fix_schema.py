from sqlalchemy import create_engine, text

# Database connection details
DB_USER = 'admin'
DB_PASS = 'admin123'
DB_HOST = '216.22.5.204'
DB_PORT = '5432'
DB_NAME = 'jupiter'
DATABASE_URI = f'postgresql://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}'

def add_primary_keys():
    engine = create_engine(DATABASE_URI)
    with engine.connect() as conn:
        tables = ['atas', 'orgaos', 'itens']
        for table in tables:
            print(f"Adding primary key to {table}...")
            try:
                # Check if id exists
                # This is a bit brute force, but safe enough for this context
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN id SERIAL PRIMARY KEY;"))
                conn.commit()
                print(f"Added 'id' PK to {table}.")
            except Exception as e:
                print(f"Could not add PK to {table} (maybe exists?): {e}")

if __name__ == "__main__":
    add_primary_keys()
