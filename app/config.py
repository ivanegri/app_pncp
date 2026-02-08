import os

class Config:
    # Database connection details
    # Database connection details
    DB_USER = os.environ.get('DB_USER', 'admin')
    DB_PASS = os.environ.get('DB_PASS', 'admin123')
    DB_HOST = os.environ.get('DB_HOST', '216.22.5.204')
    DB_PORT = os.environ.get('DB_PORT', '5432')
    DB_NAME = os.environ.get('DB_NAME', 'jupiter')
    
    SQLALCHEMY_DATABASE_URI = f'postgresql://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
