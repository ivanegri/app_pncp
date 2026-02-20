import psycopg2
from decouple import config

# Fallback to local testing credentials if .env not in current dir
DB_HOST = "localhost"
DB_NAME = "pncp_data"
DB_USER = "pncp_user"
DB_PASS = "pncp_password"

try:
    conn = psycopg2.connect(host=DB_HOST, database=DB_NAME, user=DB_USER, password=DB_PASS)
    cur = conn.cursor()
    cur.execute("SELECT valorUnitarioEstimado FROM itens WHERE descricao ILIKE '%alginato%' AND valorUnitarioEstimado > 0 ORDER BY valorUnitarioEstimado ASC LIMIT 10")
    print("Smallest prices > 0 for alginato:")
    for row in cur.fetchall():
        print(row[0])
    cur.close()
    conn.close()
except Exception as e:
    print(f"Error: {e}")
