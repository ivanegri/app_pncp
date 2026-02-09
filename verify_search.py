
import requests

def verify_search():
    try:
        # Search for a common term
        url = "http://127.0.0.1:5000/search?q=papel&type=itens"
        print(f"Requesting {url}...")
        
        response = requests.get(url)
        
        if response.status_code == 200:
            content = response.text
            if "Nenhum resultado encontrado" in content:
                print("FAILURE: No results found.")
            else:
                # Check for table rows or result cards
                if "<tr" in content or "card" in content:
                    print("SUCCESS: Results found!")
                    print(content[:500]) # Print beginning to verify
                else:
                     print("WARNING: Page loaded but no obvious results.")
        else:
            print(f"FAILURE: Status code {response.status_code}")
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    verify_search()
