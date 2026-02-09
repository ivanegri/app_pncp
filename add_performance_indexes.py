
from app import create_app, db
from sqlalchemy import text

app = create_app()

def add_indexes():
    with app.app_context():
        print("--- Adding Performance Indexes ---")
        
        indexes = [
            "CREATE INDEX IF NOT EXISTS idx_itens_unidade ON itens (\"unidadeMedida\");",
            "CREATE INDEX IF NOT EXISTS idx_itens_valor ON itens (\"valorUnitarioEstimado\");",
            "CREATE INDEX IF NOT EXISTS idx_itens_quantidade ON itens (quantidade);",
            "CREATE INDEX IF NOT EXISTS idx_itens_parent_cnpj ON itens (parent_cnpj);"
        ]
        
        with db.engine.connect() as conn:
            for sql in indexes:
                print(f"Executing: {sql}")
                try:
                    conn.execute(text(sql))
                    conn.commit()
                    print("Success.")
                except Exception as e:
                    print(f"Error: {e}")
                    
        print("--- Indexes Checked/Added ---")

if __name__ == "__main__":
    add_indexes()
