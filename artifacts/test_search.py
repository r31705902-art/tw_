import urllib.request
import urllib.parse
import json

def search_wikipedia(query):
    url = f"https://en.wikipedia.org/w/api.php?action=query&list=search&srsearch={urllib.parse.quote(query)}&format=json"
    req = urllib.request.Request(url, headers={"User-Agent": "CodexTest/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            results = data.get('query', {}).get('search', [])
            return [f"{r['title']}: {r['snippet']}" for r in results[:3]]
    except Exception as e:
        return [f"Error: {e}"]

if __name__ == "__main__":
    print("Testing Wikipedia Web API search:")
    results = search_wikipedia("James Webb Space Telescope")
    for r in results:
        print("-", r)
