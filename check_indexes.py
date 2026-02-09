
from sqlalchemy import create_engine, inspect, text
import os

DB_USER = os.environ.get('DB_USER', 'admin')
DB_PASS = os.environ.get('DB_PASS', 'admin123')
DB_HOST = os.environ.get('DB_HOST', '216.22.5.204')
DB_PORT = os.environ.get('DB_PORT', '5432')
DB_NAME = os.environ.get('DB_NAME', 'jupiter')

DATABASE_URI = f'postgresql://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}'

engine = create_engine(DATABASE_URI)
inspector = inspect(engine)

print("Indexes in 'itens':")
for idx in inspector.get_indexes('itens'):
    print(idx)

print("\nIndexes in 'atas':")
for idx in inspector.get_indexes('atas'):
    print(idx)

# Also check if it's a column just in case inspect_db missed something (unlikely but good to double check via sql)
print("\nDirect SQL check for column 'busca_descricao_idx' in 'itens':")
with engine.connect() as conn:
    result = conn.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name='itens' AND column_name='busca_descricao_idx'"))
    if result.fetchone():
        print("FOUND as a column")
    else:
        print("NOT FOUND as a column")
