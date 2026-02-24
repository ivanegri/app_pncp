import os

class Config:

    
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev_key_pncp_2026')
    
    # BigQuery Config
    GCP_PROJECT_ID = os.environ.get('GCP_PROJECT_ID', 'pncp-466018')
    GCP_DATASET_ID = os.environ.get('GCP_DATASET_ID', 'pncp_data')
