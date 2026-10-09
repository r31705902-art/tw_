import uuid
import json
import requests
=== ДАННЫЕ ДЛЯ РЕГИСТРАЦИИ ===
CLIENT_ID = "kimne78kx3ncx6brgo4mv6wki5h1ko"
EMAIL = "r31705902@gmail.com"
PASSWORD = "TwesT2passs521f"
USERNAME = "test_user_r31705"
Актуальные эндпоинты Twitch
ENDPOINTS = {
"twitch_main": "https://www.twitch.tv/",
"integrity": "https://passport.twitch.tv/integrity",
"protected_register": "https://passport.twitch.tv/protected_register",
"gql_register": "https://gql.twitch.tv/gql"
}
def log(msg):
timestamp = time.strftime("%H:%M:%S")
print(f"[{timestamp}] {msg}")
def run_diagnostics():
device_id = uuid.uuid4().hex
start_time = time.time()
code
Code
print("=" * 70)
print(" PROT V2: 15-СЕКУНДНЫЙ СКАНЕР ПОДКЛЮЧЕНИЙ И ТРЕБОВАНИЙ TWITCH")
print("=" * 70)
log(f"Сгенерирован X-Device-Id: {device_id}")

session = requests.Session()

# Базовые заголовки браузера Chrome
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Client-ID": CLIENT_ID,
    "X-Device-Id": device_id,
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
    "Origin": "https://www.twitch.tv",
    "Referer": "https://www.twitch.tv/",
    "Content-Type": "application/json"
})

# -------------------------------------------------------------------------
# ЭТАП 1: Получение первичных сессионных кук с twitch.tv (0 - 3 сек)
# -------------------------------------------------------------------------
log("\n--> [1/4] Инициализация соединения с https://www.twitch.tv (получение cookie)...")
try:
    res = session.get(ENDPOINTS["twitch_main"], timeout=5)
    log(f"Статус главной страницы: {res.status_code}")
    log(f"Получены куки: {dict(session.cookies)}")
except Exception as e:
    log(f"Ошибка получения кук: {e}")

time.sleep(2)

# -------------------------------------------------------------------------
# ЭТАП 2: Запрос токена безопасности /integrity (3 - 7 сек)
# -------------------------------------------------------------------------
log("\n--> [2/4] Проверка токена целостности (/integrity)...")
try:
    res = session.post(ENDPOINTS["integrity"], json={}, timeout=5)
    log(f"Статус Integrity: {res.status_code}")
    log(f"Заголовки ответа Integrity: {dict(res.headers)}")
    log(f"Тело ответа Integrity: {res.text}")
except Exception as e:
    log(f"Ошибка Integrity: {e}")

time.sleep(2)

# -------------------------------------------------------------------------
# ЭТАП 3: Попытка отправки на /protected_register (7 - 11 сек)
# -------------------------------------------------------------------------
log("\n--> [3/4] Отправка запроса на /protected_register...")
payload_passport = {
    "username": USERNAME,
    "password": PASSWORD,
    "email": EMAIL,
    "birthday": {"day": 15, "month": 5, "year": 1998},
    "client_id": CLIENT_ID,
    "include_strength": True
}

try:
    res = session.post(ENDPOINTS["protected_register"], json=payload_passport, timeout=5)
    log(f"Статус Protected Register: {res.status_code}")
    log("Заголовки ответа:")
    for k, v in res.headers.items():
        print(f"   {k}: {v}")
    
    log("Тело ответа (Требования сервиса):")
    try:
        print(json.dumps(res.json(), indent=4, ensure_ascii=False))
    except Exception:
        print(res.text if res.text else "<Пустое тело>")
except Exception as e:
    log(f"Ошибка Protected Register: {e}")

time.sleep(2)

# -------------------------------------------------------------------------
# ЭТАП 4: Попытка регистрации через GraphQL /gql (11 - 15 сек)
# -------------------------------------------------------------------------
log("\n--> [4/4] Отправка запроса на GraphQL (https://gql.twitch.tv/gql)...")
gql_payload = [{
    "operationName": "RegisterUser",
    "variables": {
        "input": {
            "username": USERNAME,
            "password": PASSWORD,
            "email": EMAIL,
            "birthday": {"day": 15, "month": 5, "year": 1998},
            "includeStrength": True
        }
    },
    "extensions": {
        "persistedQuery": {
            "version": 1,
            "sha256Hash": "b3e0e7a330089851722e030222a7f5a25b29f0ef77732d84a73f88d929b9594e"
        }
    }
}]

try:
    res = session.post(ENDPOINTS["gql_register"], json=gql_payload, timeout=5)
    log(f"Статус GQL: {res.status_code}")
    log("Тело ответа GraphQL:")
    try:
        print(json.dumps(res.json(), indent=4, ensure_ascii=False))
    except Exception:
        print(res.text)
except Exception as e:
    log(f"Ошибка GQL: {e}")

# Удерживаем сессию до 15 секунд
elapsed = time.time() - start_time
if elapsed < 15:
    remaining = 15 - elapsed
    log(f"\n[i] Ожидание завершения 15-секундной сессии (осталось {remaining:.1f} сек)...")
    time.sleep(remaining)

print("\n" + "=" * 70)
log("Диагностика завершена за 15 секунд.")
print("=" * 70)
if name == "main":
run_diagnostics()