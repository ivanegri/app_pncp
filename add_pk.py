
from sqlalchemy import create_engine, text
import os

# Database connection details
DB_USER = os.environ.get('DB_USER', 'admin')
DB_PASS = os.environ.get('DB_PASS', 'admin123')
DB_HOST = os.environ.get('DB_HOST', '216.22.5.204')
DB_PORT = os.environ.get('DB_PORT', '5432')
DB_NAME = os.environ.get('DB_NAME', 'jupiter')

DATABASE_URI = f'postgresql://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}'

def add_pk():
    print(f"Connecting to {DB_HOST}...")
    engine = create_engine(DATABASE_URI)
    
    with engine.connect() as conn:
        print("Connected.")
        
        # Check if 'id' column exists
        print("Checking if 'id' column exists in 'itens'...")
        check_col = conn.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name='itens' AND column_name='id'"))
        
        if not check_col.fetchone():
            print("Column 'id' MISSING. Adding it as SERIAL PRIMARY KEY...")
            try:
                conn.execute(text("ALTER TABLE itens ADD COLUMN id SERIAL PRIMARY KEY"))
                conn.commit()
                print("Primary Key added successfully.")
            except Exception as e:
                print(f"Error adding PK: {e}")
        else:
            print("Column 'id' EXISTS. Checking if it is PK...")
            # Simple check via constraint name or just try to add constraint
            # Let's try to add the constraint if not exists, or just say it exists.
            # If it exists but is not PK, automap might still fail if it's not defined as PK.
            # For now, let's assume if 'id' exists we might need to ensure it is PK.
            try:
                conn.execute(text("ALTER TABLE itens ADD PRIMARY KEY (id)"))
                conn.commit()
                print("Made 'id' the Primary Key.")
            except Exception as e:
                print(f"Could not add PK constraint (likely already exists): {e}")

if __name__ == "__main__":
    try:
        add_pk()
    except Exception as e:
        print(f"An error occurred: {e}")
