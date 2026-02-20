import os
import sys
# Need to setup app context
from app import create_app
from app.models import db

app = create_app()
with app.app_context():
    Itens = db.Model.metadata.tables['itens']
    
    # Let's query just using raw SQL to be sure
    result = db.session.execute("SELECT valorUnitarioEstimado FROM itens WHERE descricao ILIKE '%alginato%' AND valorUnitarioEstimado >= 0 ORDER BY valorUnitarioEstimado ASC LIMIT 20").fetchall()
    print("Smallest prices for alginato:")
    for row in result:
        print(row[0])
