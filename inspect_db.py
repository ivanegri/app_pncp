from app import create_app
from app.models import db, Base

app = create_app()
with app.app_context():
    try:
        Itens = Base.classes.itens
        cols = Itens.__table__.columns.keys()
        print(f"Itens columns ({len(cols)}):")
        for c in cols:
            print(f"- {c}")
    except Exception as e:
        print("Error:", e)
