from google.cloud import bigquery
from flask import current_app
import os
import json
import base64

class BigQueryClient:
    def __init__(self):
        self.client = None
        self.project_id = os.environ.get('GCP_PROJECT_ID', 'pncp-466018')
        self.dataset_id = os.environ.get('GCP_DATASET_ID', 'pncp_data')

    def get_client(self):
        if not self.client:
            # Try loading credentials from env var (base64-encoded JSON)
            creds_b64 = os.environ.get('GOOGLE_CREDENTIALS_JSON')
            if creds_b64:
                try:
                    creds_json = json.loads(base64.b64decode(creds_b64).decode('utf-8'))
                    if creds_json.get('type') == 'authorized_user':
                        from google.oauth2.credentials import Credentials
                        credentials = Credentials(
                            token=None,
                            refresh_token=creds_json['refresh_token'],
                            client_id=creds_json['client_id'],
                            client_secret=creds_json['client_secret'],
                            token_uri='https://oauth2.googleapis.com/token'
                        )
                    else:
                        from google.oauth2 import service_account
                        credentials = service_account.Credentials.from_service_account_info(creds_json)
                    self.client = bigquery.Client(project=self.project_id, credentials=credentials)
                except Exception as e:
                    print(f"Warning: Failed to load credentials from env var: {e}")
                    self.client = bigquery.Client(project=self.project_id)
            else:
                # Fallback to Application Default Credentials (local dev or GOOGLE_APPLICATION_CREDENTIALS)
                self.client = bigquery.Client(project=self.project_id)
        return self.client

    def search_items(self, query_term, limit=20, offset=0):
        client = self.get_client()
        
        # SEARCH function usage for 'itens'
        # We use SEARCH(descricao, 'query_term') which leverages the index if available
        sql = f"""
            SELECT *
            FROM `{self.project_id}.{self.dataset_id}.itens`
            WHERE SEARCH(descricao, @query_term)
            LIMIT @limit OFFSET @offset
        """
        
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("query_term", "STRING", query_term),
                bigquery.ScalarQueryParameter("limit", "INT64", limit),
                bigquery.ScalarQueryParameter("offset", "INT64", offset),
            ]
        )
        
        query_job = client.query(sql, job_config=job_config)
        results = []
        for row in query_job.result():
            results.append(dict(row))
            
        return results

    def count_items(self, query_term):
        client = self.get_client()
        sql = f"""
            SELECT COUNT(*) as total
            FROM `{self.project_id}.{self.dataset_id}.itens`
            WHERE SEARCH(descricao, @query_term)
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("query_term", "STRING", query_term)
            ]
        )
        query_job = client.query(sql, job_config=job_config)
        result = next(query_job.result())
        return result['total']

    # Add similar methods for 'atas', 'orgaos' if needed, or make generic
    def search_generic(self, table_name, search_column, query_term, limit=20, offset=0):
        client = self.get_client()
        # constructing table ref safely
        table_ref = f"`{self.project_id}.{self.dataset_id}.{table_name}`"
        
        # Use SEARCH if valid, or standard LIKE/CONTAINS
        # For simple migration, we use SEARCH for robustness if indexes exist, or simple LIKE
        # BigQuery SEARCH works on STRING columns even without index (just slower)
        
        sql = f"""
            SELECT *
            FROM {table_ref}
            WHERE SEARCH({search_column}, @query_term)
            LIMIT @limit OFFSET @offset
        """
         
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("query_term", "STRING", query_term),
                bigquery.ScalarQueryParameter("limit", "INT64", limit),
                bigquery.ScalarQueryParameter("offset", "INT64", offset),
            ]
        )
        
        query_job = client.query(sql, job_config=job_config)
        # Using [dict(row) for row in query_job] is implicitly calling result, but let's be safe
        results = [dict(row) for row in query_job.result()]
        return results

    def count_generic(self, table_name, search_column, query_term):
        client = self.get_client()
        table_ref = f"`{self.project_id}.{self.dataset_id}.{table_name}`"
        sql = f"""
            SELECT COUNT(*) as total
            FROM {table_ref}
            WHERE SEARCH({search_column}, @query_term)
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("query_term", "STRING", query_term)
            ]
        )
        query_job = client.query(sql, job_config=job_config)
        return next(query_job.result())['total']

    def get_unit_distribution(self, query_term):
        client = self.get_client()
        sql = f"""
            SELECT unidadeMedida as name, COUNT(*) as count
            FROM `{self.project_id}.{self.dataset_id}.itens`
            WHERE SEARCH(descricao, @query_term)
            GROUP BY 1
            ORDER BY 2 DESC
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("query_term", "STRING", query_term)
            ]
        )
        query_job = client.query(sql, job_config=job_config)
        return [dict(row) for row in query_job]

    def get_states(self, query_term):
        client = self.get_client()
        sql = f"""
            SELECT DISTINCT o.State as name
            FROM `{self.project_id}.{self.dataset_id}.itens` i
            JOIN `{self.project_id}.{self.dataset_id}.orgaos` o ON i.parent_cnpj = o.cnpj
            WHERE SEARCH(i.descricao, @query_term)
            AND o.State IS NOT NULL
            ORDER BY 1
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[bigquery.ScalarQueryParameter("query_term", "STRING", query_term)]
        )
        query_job = client.query(sql, job_config=job_config)
        return [row['name'] for row in query_job.result()]

    def get_regions(self, query_term):
        client = self.get_client()
        sql = f"""
            SELECT DISTINCT o.regiao as name
            FROM `{self.project_id}.{self.dataset_id}.itens` i
            JOIN `{self.project_id}.{self.dataset_id}.orgaos` o ON i.parent_cnpj = o.cnpj
            WHERE SEARCH(i.descricao, @query_term)
            AND o.regiao IS NOT NULL
            ORDER BY 1
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[bigquery.ScalarQueryParameter("query_term", "STRING", query_term)]
        )
        query_job = client.query(sql, job_config=job_config)
        return [row['name'] for row in query_job.result()]

    def get_price_stats(self, query_term, unit=None, state=None, region=None):
        client = self.get_client()
        # Basal filtering
        where_clause = "SEARCH(i.descricao, @query_term)"
        params = [bigquery.ScalarQueryParameter("query_term", "STRING", query_term)]
        
        if unit:
            where_clause += " AND i.unidadeMedida = @unit"
            params.append(bigquery.ScalarQueryParameter("unit", "STRING", unit))
        
        if state:
            where_clause += " AND o.State = @state"
            params.append(bigquery.ScalarQueryParameter("state", "STRING", state))
            
        if region:
            where_clause += " AND o.regiao = @region"
            params.append(bigquery.ScalarQueryParameter("region", "STRING", region))

        sql = f"""
            SELECT 
                AVG(i.valorUnitarioEstimado) as avg_price,
                MIN(i.valorUnitarioEstimado) as min_price,
                MAX(i.valorUnitarioEstimado) as max_price,
                SUM(i.quantidade) as total_qty,
                COUNT(*) as count_rows
            FROM `{self.project_id}.{self.dataset_id}.itens` i
            JOIN `{self.project_id}.{self.dataset_id}.orgaos` o ON i.parent_cnpj = o.cnpj
            WHERE {where_clause} AND i.valorUnitarioEstimado > 0
        """
        job_config = bigquery.QueryJobConfig(query_parameters=params)
        query_job = client.query(sql, job_config=job_config)
        result = next(query_job.result())
        return dict(result)

    def get_price_sample(self, query_term, unit=None, state=None, region=None, limit=10000):
        client = self.get_client()
        where_clause = "SEARCH(i.descricao, @query_term)"
        params = [bigquery.ScalarQueryParameter("query_term", "STRING", query_term)]
        
        if unit:
            where_clause += " AND i.unidadeMedida = @unit"
            params.append(bigquery.ScalarQueryParameter("unit", "STRING", unit))

        if state:
            where_clause += " AND o.State = @state"
            params.append(bigquery.ScalarQueryParameter("state", "STRING", state))
            
        if region:
            where_clause += " AND o.regiao = @region"
            params.append(bigquery.ScalarQueryParameter("region", "STRING", region))

        sql = f"""
            SELECT i.valorUnitarioEstimado
            FROM `{self.project_id}.{self.dataset_id}.itens` i
            JOIN `{self.project_id}.{self.dataset_id}.orgaos` o ON i.parent_cnpj = o.cnpj
            WHERE {where_clause}
            AND i.valorUnitarioEstimado > 0
            LIMIT @limit
        """
        params.append(bigquery.ScalarQueryParameter("limit", "INT64", limit))
        job_config = bigquery.QueryJobConfig(query_parameters=params)
        query_job = client.query(sql, job_config=job_config)
        return [row['valorUnitarioEstimado'] for row in query_job.result()]

    def get_top_orgaos(self, query_term, unit=None, state=None, region=None, limit=20):
        client = self.get_client()
        where_clause = "SEARCH(i.descricao, @query_term)"
        params = [bigquery.ScalarQueryParameter("query_term", "STRING", query_term)]
        
        if unit:
            where_clause += " AND i.unidadeMedida = @unit"
            params.append(bigquery.ScalarQueryParameter("unit", "STRING", unit))

        if state:
            where_clause += " AND o.State = @state"
            params.append(bigquery.ScalarQueryParameter("state", "STRING", state))
            
        if region:
            where_clause += " AND o.regiao = @region"
            params.append(bigquery.ScalarQueryParameter("region", "STRING", region))
            
        params.append(bigquery.ScalarQueryParameter("limit", "INT64", limit))

        sql = f"""
            SELECT 
                o.razaoSocial as name,
                o.cnpj,
                COUNT(i.numeroItem) as count,
                SUM(i.quantidade) as total_qty,
                AVG(i.valorUnitarioEstimado) as avg_price,
                o.City as city,
                o.State as state,
                o.regiao as region
            FROM `{self.project_id}.{self.dataset_id}.itens` i
            JOIN `{self.project_id}.{self.dataset_id}.orgaos` o
            ON i.parent_cnpj = o.cnpj
            WHERE {where_clause}
            GROUP BY 1, 2, 6, 7, 8
            ORDER BY 3 DESC
            LIMIT @limit
        """
        job_config = bigquery.QueryJobConfig(query_parameters=params)
        query_job = client.query(sql, job_config=job_config)
        return [dict(row) for row in query_job.result()]

bq_client = BigQueryClient()
