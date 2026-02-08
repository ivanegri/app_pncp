from sqlalchemy import create_engine, inspect
import os

DB_USER = os.environ.get('DB_USER', 'admin')
DB_PASS = os.environ.get('DB_PASS', 'admin123')
DB_HOST = os.environ.get('DB_HOST', '216.22.5.204')
DB_PORT = os.environ.get('DB_PORT', '5432')
DB_NAME = os.environ.get('DB_NAME', 'jupiter')

DATABASE_URI = f'postgresql://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}'

engine = create_engine(DATABASE_URI)
inspector = inspect(engine)

print("Columns in 'atas':")
for col in inspector.get_columns('atas'):
    print(col['name'])

print("\nColumns in 'itens':")
for col in inspector.get_columns('itens'):
    print(col['name'])
