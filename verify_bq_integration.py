from app.utils_bigquery import bq_client
import os

try:
    print("Testing BigQuery Client...")
    
    query = "notebook"
    
    print(f"\n1. Searching for '{query}'...")
    results = bq_client.search_items(query, limit=5)
    print(f"Found {len(results)} items.")
    if results:
        print(f"Sample: {results[0].get('descricao', 'No description')} - {results[0].get('valorUnitarioEstimado', 'No price')}")

    print(f"\n2. Counting items for '{query}'...")
    count = bq_client.count_items(query)
    print(f"Total count (specific): {count}")
    
    count_gen = bq_client.count_generic('itens', 'descricao', query)
    print(f"Total count (generic): {count_gen}")

    print(f"\n3. Unit Distribution for '{query}'...")
    units = bq_client.get_unit_distribution(query)
    print(f"Units found: {len(units)}")
    if units:
        print(f"Top unit: {units[0]}")

    print(f"\n4. Price Stats for '{query}'...")
    stats = bq_client.get_price_stats(query)
    print(f"Stats: {stats}")
    
    # print(f"\n5. Top Orgaos for '{query}'...")
    # top_orgaos = bq_client.get_top_orgaos(query)
    # print(f"Top Orgaos: {len(top_orgaos)}")
    # if top_orgaos:
    #     print(f"Top: {top_orgaos[0]}")

    print("\n✅ BigQuery Client Verification Successful!")
    
except Exception as e:
    print(f"\n❌ Verification Failed: {e}")
    import traceback
    traceback.print_exc()
