import requests

url = "https://www.twitch.tv"
try:
    response = requests.get(url)
    print("Headers:")
    for key, value in response.headers.items():
        print(f"{key}: {value}")
    
    print("\nCookies:")
    for cookie in response.cookies:
        print(f"{cookie.name}: {cookie.value}")

except Exception as e:
    print(f"Error: {e}")
