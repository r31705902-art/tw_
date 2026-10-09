import sys
import urllib.request
import urllib.parse
import re

def search_ddg(query):
    url = f"https://lite.duckduckgo.com/lite/"
    data = urllib.parse.urlencode({"q": query}).encode("utf-8")
    req = urllib.request.Request(
        url, 
        data=data,
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            html = response.read().decode('utf-8', errors='ignore')
            urls = re.findall(r'https?://[^\s"\'<>]+', html)
            github_urls = [u for u in urls if 'github.com/KhronosGroup/glslang' in u or 'github.com' in u]
            seen = set()
            unique = []
            for u in github_urls:
                clean = u.split('&')[0].rstrip(')"]}')
                if clean not in seen:
                    seen.add(clean)
                    unique.append(clean)
            return unique[:10]
    except Exception as e:
        return [f"Error searching DuckDuckGo: {e}"]

if __name__ == "__main__":
    query = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "glslangValidator KhronosGroup github releases"
    print(f"Searching DuckDuckGo for: '{query}'...\n")
    results = search_ddg(query)
    for i, res in enumerate(results, 1):
        print(f"{i}. {res}")
