from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.ext.automap import automap_base

db = SQLAlchemy()
Base = automap_base()

def init_db(app):
    db.init_app(app)
    
    with app.app_context():
        # Reflect existing tables
        Base.prepare(db.engine, reflect=True)
        print("Database tables reflected successfully.")
