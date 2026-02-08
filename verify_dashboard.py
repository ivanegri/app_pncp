import urllib.request
try:
    with urllib.request.urlopen("http://127.0.0.1:5000/dashboard?q=xyz") as response:
        html = response.read().decode('utf-8')
        print(html[:500])
except Exception as e:
    print(f"Error: {e}")
