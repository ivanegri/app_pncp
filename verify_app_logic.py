
from app import create_app, db
from sqlalchemy import text

app = create_app()

def test_query():
    with app.app_context():
        # Simulate the search route logic
        query_term = "hidrocoloide"
        
        # Force reflection in this script context
        from app.models import Base
        print("inspecting engine...")
        from sqlalchemy import inspect
        insp = inspect(db.engine)
        print("Tables in DB:", insp.get_table_names())
        
        print("Reflecting tables...")
        Base.prepare(db.engine, reflect=True)
        
        if 'itens' not in Base.classes:
            print("Error: 'itens' class not found in Base.classes after reflection")
            print("Available classes:", list(Base.classes.keys()))
            return

        Itens = Base.classes.itens
        
        print(f"\n--- Testing App Query Logic for '{query_term}' ---")
        
        fts_condition = text("busca_descricao_idx @@ websearch_to_tsquery('portuguese', :q)")
        query = db.session.query(Itens).filter(fts_condition)
        
        # Count
        count = query.params(q=query_term).count()
        print(f"SQLAlchemy Count: {count}")
        
        if count > 0:
            results = query.params(q=query_term).limit(5).all()
            print(f"Found {len(results)} items.")
            print("First item:", results[0].descricao)
        else:
            print("No results found via SQLAlchemy.")

if __name__ == "__main__":
    test_query()
