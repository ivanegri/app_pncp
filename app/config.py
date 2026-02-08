import os

class Config:
    # Database connection details
    DB_USER = 'admin'
    DB_PASS = 'admin123'
    DB_HOST = '216.22.5.204'
    DB_PORT = '5432'
    DB_NAME = 'jupiter'
    
    SQLALCHEMY_DATABASE_URI = f'postgresql://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
