from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
from google.cloud import bigquery
import os

def _get_bq():
    """Retorna o cliente BigQuery com credenciais configuradas via GOOGLE_CREDENTIALS_JSON."""
    from .utils_bigquery import bq_client
    return bq_client.get_client(), bq_client.project_id, bq_client.dataset_id

class User(UserMixin):
    def __init__(self, id=None, email=None, name=None, password_hash=None, created_at=None, role='user', tier='free'):
        self.id = id
        self.email = email
        self.name = name
        self.password_hash = password_hash
        self.created_at = created_at if created_at else datetime.utcnow()
        self.role = role
        self.tier = tier

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, password)

    @classmethod
    def get(cls, user_id):
        client, project_id, dataset_id = _get_bq()
        query = f"SELECT * FROM `{project_id}.{dataset_id}.users` WHERE id = @user_id LIMIT 1"
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("user_id", "INTEGER", int(user_id))
            ]
        )
        results = list(client.query(query, job_config=job_config).result())
        if results:
            r = results[0]
            return cls(r.id, r.email, r.name, r.password_hash, r.created_at, r.role, r.tier)
        return None

    @classmethod
    def find_by_email(cls, email):
        client, project_id, dataset_id = _get_bq()
        query = f"SELECT * FROM `{project_id}.{dataset_id}.users` WHERE email = @email LIMIT 1"
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("email", "STRING", email)
            ]
        )
        results = list(client.query(query, job_config=job_config).result())
        if results:
            r = results[0]
            return cls(r.id, r.email, r.name, r.password_hash, r.created_at, r.role, r.tier)
        return None

    @classmethod
    def get_all(cls):
        client, project_id, dataset_id = _get_bq()
        query = f"SELECT * FROM `{project_id}.{dataset_id}.users` ORDER BY created_at DESC"
        results = list(client.query(query).result())
        return [cls(r.id, r.email, r.name, r.password_hash, r.created_at, r.role, r.tier) for r in results]

    def save(self):
        client, project_id, dataset_id = _get_bq()
        table_id = f"{project_id}.{dataset_id}.users"

        if self.id is None:
            max_id_query = f"SELECT IFNULL(MAX(id), 0) + 1 AS next_id FROM `{table_id}`"
            max_id_result = list(client.query(max_id_query).result())
            self.id = max_id_result[0].next_id

            insert_query = f"""
                INSERT INTO `{table_id}` (id, email, name, password_hash, created_at, role, tier)
                VALUES (@id, @email, @name, @password_hash, @created_at, @role, @tier)
            """
            job_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("id", "INTEGER", self.id),
                    bigquery.ScalarQueryParameter("email", "STRING", self.email),
                    bigquery.ScalarQueryParameter("name", "STRING", self.name),
                    bigquery.ScalarQueryParameter("password_hash", "STRING", self.password_hash),
                    bigquery.ScalarQueryParameter("created_at", "TIMESTAMP", self.created_at),
                    bigquery.ScalarQueryParameter("role", "STRING", self.role),
                    bigquery.ScalarQueryParameter("tier", "STRING", self.tier),
                ]
            )
            client.query(insert_query, job_config=job_config).result()
        else:
            update_query = f"""
                UPDATE `{table_id}`
                SET email = @email,
                    name = @name,
                    password_hash = @password_hash,
                    role = @role,
                    tier = @tier
                WHERE id = @id
            """
            job_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("id", "INTEGER", self.id),
                    bigquery.ScalarQueryParameter("email", "STRING", self.email),
                    bigquery.ScalarQueryParameter("name", "STRING", self.name),
                    bigquery.ScalarQueryParameter("password_hash", "STRING", self.password_hash),
                    bigquery.ScalarQueryParameter("role", "STRING", self.role),
                    bigquery.ScalarQueryParameter("tier", "STRING", self.tier),
                ]
            )
            client.query(update_query, job_config=job_config).result()

def init_db(app):
    print("PostgreSQL disabled, using BigQuery only.")
