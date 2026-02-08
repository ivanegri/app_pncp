from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.ext.automap import automap_base
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime

db = SQLAlchemy()
Base = automap_base()

class User(UserMixin, db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    name = db.Column(db.String(150), nullable=True)
    password_hash = db.Column(db.String(256), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    role = db.Column(db.String(20), default='user') # 'admin', 'user'
    tier = db.Column(db.String(20), default='free') # 'free', 'starter', 'full'

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

def init_db(app):
    db.init_app(app)
    
    with app.app_context():
        # Create tables first (for User model)
        db.create_all()
        
        # Reflect existing tables (from PNCP db)
        Base.prepare(db.engine, reflect=True)
        print("Database initialized (User table created & external tables reflected).")
