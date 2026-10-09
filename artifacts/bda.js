/* ======================================================================== *
 * 1. КОНСТАНТЫ И КОНФИГУРАЦИЯ СЕССИИ (Модуль 4876)
 * ======================================================================== */
CONST CAPI_VERSION    = "2.18.0";
CONST ENFORCEMENT_HASH = "837917397f9ce5fc720def2e31248537";
CONST DOMAIN_FALLBACK  = "arkoselabs.com";

CONST ENDPOINTS = {
  SETTINGS:  "/v2/:key/settings",
  SETUP_KEY: "/fc/gt2/public_key/:public_key",
  METRICS:   "/metrics/ui"
};

CONST EVENTS = {
  SHOW_ENFORCEMENT: "show enforcement",
  CHALLENGE_SHOW:   "challenge shown",
  COMPLETED:        "challenge completed",
  FAILED:           "challenge failed",
  SUPPRESSED:       "challenge suppressed"
};

/* ======================================================================== *
 * 2. ДВИЖОК СБОРА СИГНАЛОВ (FINGERPRINTING ENGINE - zr)
 * ======================================================================== */
FUNCTION collectBrowserFingerprint(pageLevelConfig, userOptions) {
  VAR fp = {};

  // 1. Стандартные системные метрики
  fp["DNT"]  = navigator.doNotTrack || window.doNotTrack || "unknown";
  fp["L"]    = navigator.language || navigator.userLanguage || "";
  fp["D"]    = screen.colorDepth || -1;
  fp["PR"]   = window.devicePixelRatio || 1;
  fp["S"]    = getScreenResolutionSorted();   // Width x Height
  fp["AS"]   = getAvailScreenResolution();   // AvailWidth x AvailHeight
  fp["TO"]   = (NEW Date()).getTimezoneOffset();
  fp["SS"]   = checkSessionStorageSupport();
  fp["LS"]   = checkLocalStorageSupport();
  fp["IDB"]  = checkIndexedDBSupport();
  fp["B"]    = !!document.body;
  fp["ODB"]  = !!window.openDatabase;
  fp["CPUC"] = navigator.cpuClass || "unknown";
  fp["PK"]   = navigator.platform || "unknown";
  fp["H"]    = navigator.hardwareConcurrency || "unknown";

  // 2. Сложные системные отпечатки (Canvas & WebGL)
  fp["CFP"]  = renderCanvas2DFingerprint();  // Рисует градиенты, эмодзи 😃, текст, возвращает MurmurHash3
  fp["FR"]   = checkScreenAspectRatioAnomaly();
  fp["FOS"]  = detectOperatingSystemAnomalies();
  fp["FB"]   = detectBrowserEngineAnomalies();
  fp["JSF"]  = inspectFunctionToStringAnomalies();
  fp["P"]    = getInstalledPluginsList();
  fp["T"]    = getTouchSupportCapabilities();
  fp["SWF"]  = typeof window.ServiceWorker !== "undefined";

  // 3. Асинхронный параллельный сбор через Promise.all
  VAR asyncSignals = AWAIT Promise.all([
    collectAudioFingerprint(),       // Синтезирует аудио-волну через OfflineAudioContext
    collectBatteryInfo(),            // navigator.getBattery()
    collectPermissionsStatus(),      // navigator.permissions.query()
    collectMediaDevicesList(),       // navigator.mediaDevices.enumerateDevices()
    collectSpeechVoicesList(),       // speechSynthesis.getVoices()
    collectKeyboardLayout()          // navigator.keyboard.getLayout()
  ]);

  // Упаковка всех собранных данных
  VAR finalFP = {
    f:   hashObjectKeys(fp, ";"),
    f_h: MurmurHash3_128(JSON.stringify(fp)),
    ef:  mergeAsyncSignals(asyncSignals),
    w:   getIframeDimensions(),
    js:  collectGlobalPropertiesAndPrototypeChain()
  };

  RETURN finalFP;
}

/* 2.1 Отрисовка Canvas Fingerprint */
FUNCTION renderCanvas2DFingerprint() {
  TRY {
    VAR canvas = document.createElement("canvas");
    canvas.width = 200; canvas.height = 200;
    VAR ctx = canvas.getContext("2d");

    ctx.textBaseline = "top";
    ctx.font = "14px 'Arial'";
    ctx.fillStyle = "#f60";
    ctx.fillRect(125, 1, 62, 20);

    ctx.fillStyle = "#069";
    ctx.fillText("Cwm fjord bank glyphs vex, 😃", 2, 15);
    ctx.fillStyle = "rgba(102, 204, 0, 0.7)";
    ctx.fillText("Cwm fjord bank glyphs vex, 😃", 4, 45);

    // Добавление дуг и градиентов
    ctx.beginPath();
    ctx.arc(75, 75, 50, 0, Math.PI * 2, TRUE);
    ctx.closePath();
    ctx.fill();

    VAR dataURL = canvas.toDataURL();
    RETURN MurmurHash3_128(dataURL);
  } CATCH {
    RETURN null;
  }
}

/* ======================================================================== *
 * 3. АЛГОРИТМ ШИФРОВАНИЯ ВХОДНЫХ ДАННЫХ (BDA ENCRYPTION - jn)
 * ======================================================================== */
FUNCTION encryptBrowserData(bdaData, publicKey) {
  VAR timestamp = Math.floor((NEW Date()).getTime() / 1000);
  VAR userAgent = navigator.userAgent;
  
  // Выравнивание временной метки по окну 21600 сек (6 часов)
  VAR timeSlot = Math.round(timestamp - (timestamp % 21600));
  VAR encryptionSecret = userAgent + timeSlot;

  // Генерация случайных соли и вектор инициализации (IV)
  VAR iv = window.crypto.getRandomValues(NEW Uint8Array(16));
  VAR salt = window.crypto.getRandomValues(NEW Uint8Array(8));
  
  VAR hexIV = bytesToHex(iv);
  VAR hexSalt = bytesToHex(salt);

  // Вывод деривативного ключа через PBKDF2 / Custom Hash (kn)
  VAR derivedKey = deriveKey(encryptionSecret, hexSalt);

  VAR serializedPayload = JSON.stringify(bdaData);
  VAR rawDataBytes = stringToUint8Array(serializedPayload);

  VAR encryptedBytes;

  IF (window.crypto.subtle) {
    // Шифрование через WebCrypto API (AES-CBC)
    VAR cryptoKey = AWAIT window.crypto.subtle.importKey("raw", derivedKey, "AES-CBC");
    encryptedBytes = AWAIT window.crypto.subtle.encrypt({ name: "AES-CBC", iv: iv }, cryptoKey, rawDataBytes);
  } ELSE {
    // Резервный фоллбек на CryptoJS / JS RSA-OAEP
    encryptedBytes = fallbackCryptoJS(derivedKey, iv, rawDataBytes);
  }

  // Упаковка в Base64
  VAR payloadObject = {
    ct: bytesToBase64(encryptedBytes),
    iv: hexIV,
    s:  hexSalt
  };

  RETURN {
    data: Base64.encode(JSON.stringify(payloadObject)),
    timestamp: timeSlot
  };
}

/* ======================================================================== *
 * 4. ИНИЦИАЛИЗАЦИЯ СЕССИИ И СЕТЕВОЙ ЗАПРОС (be -> ae)
 * ======================================================================== */
FUNCTION setupCaptchaSession(config) {
  VAR url = config.domain + "/fc/gt2/public_key/" + config.publicKey;

  // Формирование параметров запроса
  VAR bodyParams = [
    "api_type=js",
    "public_key=" + config.publicKey,
    "bda=" + config.encryptedFPData,
    "site=" + encodeURIComponent(window.location.origin),
    "userbrowser=" + encodeURIComponent(navigator.userAgent),
    "capi_version=" + CAPI_VERSION,
    "capi_mode=" + config.capiMode,
    "style_theme=" + config.styleTheme,
    "rnd=" + Math.random()
  ];

  // Извлечение сохраненных токенов из IndexedDB / LocalStorage (x-ark-esync-value)
  VAR persistentData = AWAIT loadFromIndexedDBOrLocalStorage("key-val-store");
  VAR headers = {
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"
  };
  IF (persistentData) {
    headers["x-ark-esync-value"] = persistentData;
  }

  // Отправка POST запроса
  VAR response = AWAIT fetchWithTimeout(url, {
    method: "POST",
    headers: headers,
    body: bodyParams.join("&")
  });

  VAR responseData = AWAIT response.json();

  // Сохранение полученных заголовков синхронизации обратно в хранилище
  IF (response.headers.get("x-ark-esync-value")) {
    AWAIT saveToIndexedDBOrLocalStorage("key-val-store", response.headers.get("x-ark-esync-value"));
  }

  // Если сервер вернет флаги биометрии/PoW:
  IF (responseData.mbio) window.ae.mouse_biometrics = TRUE;
  IF (responseData.tbio) window.ae.touch_biometrics = TRUE;
  IF (responseData.kbio) window.ae.keyboard_biometrics = TRUE;

  // Вставка скрытых инпутов и подгрузка game_core (игры)
  injectHiddenFormInputs(responseData);
  RETURN responseData;
}

/* ======================================================================== *
 * 5. УПРАВЛЕНИЕ ИНТЕРФЕЙСОМ И POSTMESSAGE (de, po)
 * ======================================================================== */
FUNCTION initDOMAndEventListeners(callbacks) {
  // Прослушивание сообщений от запущенной внутри iframe капчи
  window.addEventListener("message", FUNCTION(event) {
    VAR msg;
    TRY { msg = JSON.parse(event.data).message; } CATCH { msg = event.data; }

    SWITCH (msg) {
      CASE "finished_loading_game":
        callbacks.onLoaded();
        BREAK;

      CASE "complete":
        VAR token = getVerificationTokenInput();
        callbacks.onCompleted(token);
        BREAK;

      CASE "session_failed":
        VAR token = getVerificationTokenInput();
        callbacks.onFailed(token, event.data.payload.reason);
        BREAK;

      CASE "session_timeout":
      CASE "restart":
      CASE "fc_hard_reload":
        callbacks.onReset();
        BREAK;

      CASE "error":
        callbacks.onError(event.data.payload);
        BREAK;
    }
  });
}

/* Основная точка входа после загрузки */
FUNCTION runEnforcementEngine() {
  // 1. Сбор отпечатка браузера
  VAR fp = AWAIT collectBrowserFingerprint(window.ae.configData);

  // 2. Шифрование BDA
  VAR encrypted = AWAIT encryptBrowserData(fp, PUBLIC_KEY);

  // 3. Запрос сессии капчи
  VAR session = AWAIT setupCaptchaSession({
    publicKey: PUBLIC_KEY,
    encryptedFPData: encrypted.data,
    domain: "https://client-api.arkoselabs.com"
  });

  // 4. Отрисовка фрейма игры
  renderChallengeIframeContainer(session);
}

// Запуск при готовности
runEnforcementEngine();


[ Браузер / Скрипт ]
       │
       ├──> 1. Сбор BDA (Bot Detection Attribute): ~30+ параметров браузера, Canvas, Audio, Fonts.
       ├──> 2. Вычисление MurmurHash3_128 для контрольных сумм отпечатка.
       ├──> 3. Шифрование BDA: AES-CBC + MD5 PBKDF2 (Ключ = UserAgent + 6-часовой квант времени).
       ├──> 4. POST-запрос на /fc/gt2/public_key/<public_key> (с заголовками x-ark-esync-value).
       │
       ▼
[ Сервер Arkose Labs ]
       │
       ├──> Анализ BDA + IP + Заголовки HTTP + TLS Fingerprint (JA3/JA4).
       │
       ├───> [ РИСК НИЗКИЙ ]  ──> Возвращает: { "suppressed": true, "token": "..." } ──> [УСПЕХ ВБИУСУЮ]
       └───> [ РИСК ВЫСОКИЙ ] ──> Возвращает: { "challenge_url": "game.js" }      ──> [ТРЕБУЕТСЯ 3D-ИГРА]


1. Формирование структуры BDA (Массив параметров)

Скрипт собирает ключевые параметры в массив объектов {key: ..., value: ...}:

// Внутри функции отправки событий gA:
VAR o = oo.fpData; // Данные отпечатка, собранные функцией zr()
VAR l = Qr(o.f, true); // Преобразование f-ключей в массив пар ключ-значение

VAR r = [
  { key: "api_type",    value: "js" },
  { key: "f",           value: o.f_h }, // MurmurHash3_128 от всего BDA объекта
  { key: "n",           value: Xr.encode(Math.floor(Date.now() / 1000).toString()) }, // Base64 от Unix timestamp
  { key: "wh",          value: o.w },   // Размеры окна/экрана
  { key: "enhanced_fp", value: Qr(o.ef) }, // Асинхронные сигналы (AudioContext, Battery, Voices)
  { key: "fe",          value: l },     // Массив фич браузера
  { key: "ife_hash",    value: Murmur3_128(l.join(", "), 38) }, // Хеш от фич с сидом 38
  { key: "jsbd",        value: o.js },   // Детект окружения Node/Puppeteer/Selenium
  { key: "c",           value: "FunCaptcha" }
];

// Передача массива r в функцию шифрования jn()
VAR encryptedResult = AWAIT jn(r);

2. Функция деривации ключа шифрования (kn)

Ключ шифрования не статический — он генерируется на лету из
User-Agent, 6-часового временного интервала и соли:

VAR kn = function(secretString, hexSalt) {
  // secretString = UserAgent + (Math.round(now - (now % 21600)))
  VAR combinedSeed = secretString + convertHexToCharString(hexSalt);
  
  VAR hashArray = [];
  // Первый раунд MD5 хеширования
  hashArray[0] = md5.hashBinary(combinedSeed, true);
  VAR finalHash = hashArray[0];
  
  // 2 дополнительных раунда MD5 для усложнения
  for (VAR i = 1; i < 3; i++) {
    hashArray[i] = md5.hashBinary(hashArray[i - 1] + combinedSeed, true);
    finalHash += hashArray[i];
  }
  
  // Возвращаем первые 32 байта для ключа AES-256
  RETURN stringToUint8Array(finalHash.substr(0, 32));
};

3. Главная функция шифрования BDA (jn)

Принимает массив BDA, шифрует его по алгоритму AES-CBC и упаковывает в Base64:

VAR jn = FUNCTION(bdaArray) {
  VAR now = (NEW Date()).getTime() / 1000;
  VAR userAgent = navigator.userAgent;
  
  // Округление времени до 6-часового кванта (21600 сек)
  VAR timeQuantum = Math.round(now - (now % 21600));
  VAR secretString = userAgent + timeQuantum;

  // Генерация 16 байт IV и 8 байт Salt через WebCrypto API
  VAR rawIV = window.crypto.getRandomValues(NEW Uint8Array(16));
  VAR rawSalt = window.crypto.getRandomValues(NEW Uint8Array(8));

  VAR hexIV = bytesToHex(rawIV);
  VAR hexSalt = bytesToHex(rawSalt);

  // Вычисление ключа AES
  VAR derivedKey = kn(secretString, hexSalt);
  
  VAR jsonBDA = JSON.stringify(bdaArray);
  VAR bdaBytes = stringToUint8Array(jsonBDA);

  // Шифрование данных алгоритмом AES-CBC
  VAR cipherTextBytes = AWAIT window.crypto.subtle.encrypt(
    { name: "AES-CBC", iv: rawIV },
    derivedKey,
    bdaBytes
  );

  // Упаковка в итоговую JSON-строку
  VAR encryptedPayload = JSON.stringify({
    ct: bytesToBase64(cipherTextBytes),
    s:  hexSalt,
    iv: hexIV
  });

  // Финальный Base64 от зашифрованного JSON
  RETURN {
    data: Base64.encode(encryptedPayload),
    timestamp: timeQuantum
  };
};

4. Сетевой запрос на получения токена (ae)

Формирует POST-запрос с отправкой зашифрованного BDA:

VAR ae = FUNCTION(domain, publicKey, encryptedBDA, timestamp) {
  VAR endpoint = domain + "/fc/gt2/public_key/" + publicKey;

  // Формирование Body (application/x-www-form-urlencoded)
  VAR body = [
    "public_key=" + publicKey,
    "bda=" + encodeURIComponent(encryptedBDA),
    "site=" + encodeURIComponent(window.location.origin),
    "userbrowser=" + encodeURIComponent(navigator.userAgent),
    "capi_version=2.18.0",
    "capi_mode=inline",
    "style_theme=default",
    "rnd=" + Math.random()
  ].join("&");

  VAR headers = {
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"
  };

  // Чтение токена эмуляции браузера из LocalStorage / IndexedDB (если есть)
  VAR syncHeader = AWAIT ne("key-val-store");
  IF (syncHeader) {
    headers["x-ark-esync-value"] = syncHeader;
  }

  VAR response = AWAIT fetch(endpoint, {
    method: "POST",
    headers: headers,
    body: body
  });

  VAR jsonResponse = AWAIT response.json();
  
  // Сохранение полученного заголовка x-ark-esync-value для будущих запросов
  IF (response.headers.get("x-ark-esync-value")) {
    AWAIT oe("key-val-store", response.headers.get("x-ark-esync-value"));
  }

  RETURN jsonResponse; // Содержит { token: "...", suppressed: true/false }
};

📝 3. Итоговый Псевдокод (Complete Solver Pipeline)

Этот псевдокод демонстрирует, как написать автономный генератор/решатель
невидимой капчи (например, на Python или Node.js):

# ПСЕВДОКОД: Автономный Solver невидимой капчи Arkose Labs

FUNCTION SolveInvisibleArkoseCaptcha(PUBLIC_KEY, TARGET_SITE, USER_AGENT):

    # 1. СБОР FINGERPRINT (BDA)
    # Формируем структуру сигналов точь-в-точь как оригинальный zr()
    fp_data = {
        "DNT": "unknown",
        "L": "ru-RU",
        "D": 24,
        "PR": 1.25,
        "S": "1080,1920",
        "AS": "1040,1920",
        "TO": -300,
        "SS": True, "LS": True, "IDB": True, "B": True, "ODB": False,
        "CPUC": "unknown",
        "PK": "Win32",
        "CFP": "a3f89012b...",  # MurmurHash3_128 от сгенерированного Canvas2D
        "FR": False, "FOS": "Windows", "FB": "Chrome", "JSF": False,
        "H": 8, "SWF": True
    }

    # Вычисление MurmurHash3_128 от отпечатка
    f_hash = MurmurHash3_128(JSON.stringify(fp_data))
    
    # Сборка массива BDA параметров
    bda_array = [
        {"key": "api_type",    "value": "js"},
        {"key": "f",           "value": f_hash},
        {"key": "n",           "value": Base64.encode(CURRENT_UNIX_TIMESTAMP_STR)},
        {"key": "wh",          "value": "1920|1080"},
        {"key": "enhanced_fp", "value": []},
        {"key": "fe",          "value": extractFeatureKeys(fp_data)},
        {"key": "ife_hash",    "value": MurmurHash3_128(featureKeysString, seed=38)},
        {"key": "jsbd",        "value": "{\"HL\":1,\"DT\":\"\",\"DT\":1}"},
        {"key": "c",           "value": "FunCaptcha"}
    ]

    # 2. ГЕНЕРАЦИЯ КЛЮЧА И IV
    now = CURRENT_UNIX_TIMESTAMP_SECONDS
    time_quantum = Math.round(now - (now % 21600))  # 6-часовое окно
    secret_string = USER_AGENT + time_quantum
    
    raw_iv = RandomBytes(16)   # 16 случайных байт
    raw_salt = RandomBytes(8)  # 8 случайных байт
    
    hex_iv = BytesToHex(raw_iv)
    hex_salt = BytesToHex(raw_salt)

    # 3. ДЕРИВАЦИЯ КЛЮЧА (3-кратный MD5)
    derived_key = MD5_PBKDF(secret_string, hex_salt)

    # 4. ШИФРОВАНИЕ AES-256-CBC
    json_bda = JSON.stringify(bda_array)
    cipher_bytes = AES_CBC_Encrypt(json_bda, key=derived_key, iv=raw_iv)

    payload_json = JSON.stringify({
        "ct": BytesToBase64(cipher_bytes),
        "s": hex_salt,
        "iv": hex_iv
    })

    final_bda_base64 = Base64.encode(payload_json)

    # 5. ОТПРАВКА POST-ЗАПРОСА
    http_headers = {
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "User-Agent": USER_AGENT,
        "Origin": TARGET_SITE,
        "Referer": TARGET_SITE
    }

    post_data = {
        "public_key": PUBLIC_KEY,
        "bda": final_bda_base64,
        "site": TARGET_SITE,
        "userbrowser": USER_AGENT,
        "capi_version": "2.18.0",
        "capi_mode": "inline",
        "style_theme": "default",
        "rnd": RandomFloat()
    }

    response = HTTP_POST("https://client-api.arkoselabs.com/fc/gt2/public_key/" + PUBLIC_KEY, 
                          headers=http_headers, 
                          data=UrlEncode(post_data))

    # 6. АНАЛИЗ ОТВЕТА
    res_json = JSON.parse(response.body)

    IF res_json.token IS NOT NULL AND res_json.challenge_url IS NULL:
        PRINT("[SUCCESS] Невидимая капча решена без показа игры!")
        RETURN res_json.token
    ELSE:
        PRINT("[CHALLENGE] Сервер потребует решение визуальной 3D-игры.")
        RETURN NULL

⚠️ Важные нюансы при эмуляции (Что критично):

1.  User-Agent Alignment: User-Agent, передаваемый в HTTP-заголовке, ОБЯЗАН быть
    идентичным той строке User-Agent, которая используется внутри secret_string
    при создании AES-ключа. Если они различаются хоть на один символ — сервер
    Arkose не сможет расшифровать BDA и выдаст ошибку 401 / Invalid BDA.

2.  MurmurHash3_128: В коде применяется 128-битный хэш MurmurHash3 (модуль 284).
    Если вы генерируете Canvas-слепок или ife_hash, хеш должен точно
    соответствовать реализации из файла 284.js.

3.  Заголовок x-ark-esync-value: При первом запросе сервер отдаёт в заголовке
    ответа токен идентификации сессии устройства. В последующих запросах его
    нужно отправлять обратно — это повышает «доверие» (score) к вашему IP и
    браузеру, делая капчу невидимой почти в 100% случаев.
