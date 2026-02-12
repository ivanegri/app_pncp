from app.utils_bigquery import bq_client
import concurrent.futures
import time

query_term = "alginato"
selected_unit = None
selected_state = None
selected_region = None

print("Starting reproduction script...")

try:
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        print("Submitting tasks...")
        future_units = executor.submit(bq_client.get_unit_distribution, query_term)
        future_states = executor.submit(bq_client.get_states, query_term)
        future_regions = executor.submit(bq_client.get_regions, query_term)
        
        future_stats = executor.submit(bq_client.get_price_stats, query_term, selected_unit, selected_state, selected_region)
        future_prices = executor.submit(bq_client.get_price_sample, query_term, selected_unit, selected_state, selected_region)
        future_top_orgaos = executor.submit(bq_client.get_top_orgaos, query_term, selected_unit, selected_state, selected_region)
        
        future_global_count = executor.submit(bq_client.count_items, query_term)

        print("Waiting for results...")
        units = future_units.result()
        print(f"Units: {len(units)}")
        states = future_states.result()
        print(f"States: {len(states)}")
        regions = future_regions.result()
        print(f"Regions: {len(regions)}")
        stats = future_stats.result()
        print(f"Stats: {stats}")
        prices = future_prices.result()
        print(f"Prices sample size: {len(prices)}")
        top_orgaos = future_top_orgaos.result()
        print(f"Top Orgaos: {len(top_orgaos)}")
        
        total_items_global = future_global_count.result()
        print(f"Total items global: {total_items_global}")

    print("Success!")

except Exception as e:
    print(f"Error caught: {e}")
    import traceback
    traceback.print_exc()
