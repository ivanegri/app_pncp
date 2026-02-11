from app.utils_bigquery import bq_client
import sys

query_term = "mepilex"

print(f"--- Testing get_states('{query_term}') ---")
try:
    states = bq_client.get_states(query_term)
    print(f"States found ({len(states)}): {states}")
except Exception as e:
    print(f"Error in get_states: {e}")

print(f"\n--- Testing get_regions('{query_term}') ---")
try:
    regions = bq_client.get_regions(query_term)
    print(f"Regions found ({len(regions)}): {regions}")
except Exception as e:
    print(f"Error in get_regions: {e}")

print(f"\n--- Testing get_price_stats('{query_term}') NO FILTERS ---")
stats_global = bq_client.get_price_stats(query_term)
print(f"Global stats: {stats_global}")

print(f"\n--- Testing get_price_stats('{query_term}', state='SP') ---")
stats_sp = bq_client.get_price_stats(query_term, state='SP')
print(f"SP stats: {stats_sp}")

if stats_global == stats_sp:
    print("\nWARNING: Stats are identical! Filter might not be working.")
    # Check if SP is actually the only state?
    if len(states) > 1 and 'SP' in states:
         print("And there are multiple states, so they should differ.")

print(f"\n--- Testing get_price_stats('{query_term}', state='GO') ---")
stats_go = bq_client.get_price_stats(query_term, state='GO')
print(f"GO stats: {stats_go}")
