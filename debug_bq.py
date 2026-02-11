from app.utils_bigquery import bq_client
bq = bq_client
client = bq.get_client()

sql = f'''
SELECT i.parent_cnpj, o.CNPJ, o.State, o.regiao
FROM `{bq.project_id}.{bq.dataset_id}.itens` i
LEFT JOIN `{bq.project_id}.{bq.dataset_id}.orgaos` o ON i.parent_cnpj = o.CNPJ
WHERE i.descricao LIKE "%mepilex%"
LIMIT 10
'''
results = list(client.query(sql).result())
for r in results:
    print(r)
