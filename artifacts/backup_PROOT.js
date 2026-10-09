const crypto = require('crypto');
const { Session, ClientIdentifier, initTLS, destroyTLS } = require("node-tls-client");
const { Solver } = require('arkose-solver');

// === НАСТРОЙКИ KASADA / TWITCH ===
const CONFIG = {
    mfcUrl: "https://k.twitchcdn.net/149e9513-01fa-4fb0-aad4-566afd725d1b/2d206a39-8ed7-437e-a3be-862e0f06eea3/mfc",
    integrityUrl: "https://gql.twitch.tv/integrity", 
    registerUrl: "https://passport.twitch.tv/protected_register",
    
    clientId: "kimne78kx3ncx6brgo4mv6wki5h1ko",
    clientVersion: "b3c382ac-5d5d-4d76-98f2-b05bbd59bf18",
    kasadaVersion: "j-1.2.522",
    epd: "7ae9906d03439b1173e98ddb9342a718a535ab115a7f27138cd183737d7f7afe",

    deviceId: crypto.randomUUID().replace(/-/g, ''),
    sessionId: crypto.randomBytes(16).toString('hex'),

    account: {
        email: `test_${crypto.randomBytes(4).toString('hex')}@gmail.com`,
        password: "SuperPassword123!",
        username: `User_${crypto.randomBytes(4).toString('hex')}`,
        birthday: { day: 15, month: 5, year: 1998 }
    }
};

const USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36";

function log(msg) {
    const timestamp = new Date().toLocaleTimeString('ru-RU', { hour12: false });
    console.log(`[${timestamp}] ${msg}`);
}

function logHttp(stepName, type, url, headers, body) {
    console.log(`\n==================== [${stepName} | ${type}] ====================`);
    console.log(`[URL]: ${url}`);
    console.log(`[HEADERS]:`, JSON.stringify(headers, null, 2));
    if (body !== undefined && body !== null) {
        let printBody = body;
        if (typeof body === 'string' && body.length > 1000) {
            printBody = body.substring(0, 1000) + `... [обрезано ${body.length} символов]`;
        }
        console.log(`[BODY]:`, printBody);
    }
    console.log(`================================================================\n`);
}

// УНИВЕРСАЛЬНЫЙ ИЗВЛЕКАТЕЛЬ ТОКЕНОВ (Извлекает ct, h, r из Headers и Set-Cookie)
function extractKasadaTokens(headers) {
    let ctToken = null;
    let hToken = null;
    let rToken = null;

    if (!headers) return { ctToken, hToken, rToken };

    for (const [key, val] of Object.entries(headers)) {
        const lowerKey = key.toLowerCase();

        // 1. Прямая проверка заголовков
        if (lowerKey === 'x-kpsdk-ct') ctToken = Array.isArray(val) ? val[0] : String(val);
        if (lowerKey === 'x-kpsdk-h') hToken = Array.isArray(val) ? val[0] : String(val);
        if (lowerKey === 'x-kpsdk-r') rToken = Array.isArray(val) ? val[0] : String(val);

        // 2. ПОИСК ВНУТРИ SET-COOKIE
        if (lowerKey === 'set-cookie') {
            const cookieArray = Array.isArray(val) ? val : [val];
            for (const cookie of cookieArray) {
                const ctMatch = cookie.match(/x-kpsdk-ct=([^;]+)/i);
                if (ctMatch && ctMatch[1]) ctToken = ctMatch[1];

                const hMatch = cookie.match(/x-kpsdk-h=([^;]+)/i);
                if (hMatch && hMatch[1]) hToken = hMatch[1];
            }
        }
    }
    return { ctToken, hToken, rToken };
}

function sha256(str) {
    return crypto.createHash('sha256').update(str, 'utf8').digest('hex');
}

function evalHashScore(hashStr) {
    const val = parseInt(hashStr.substring(0, 13), 16);
    return Math.pow(2, 52) / (val + 1);
}

function solveKasadaPow(taskId, targetDifficulty = 10, rounds = 2, workTime = 30, epd = CONFIG.epd) {
    let inputSeed = `tp-v2-input, ${workTime}, ${taskId}`;
    if (epd) inputSeed += `, ${epd}`;

    let currentHash = sha256(inputSeed);
    const targetThreshold = targetDifficulty / rounds;
    const answers = [];

    for (let round = 0; round < rounds; round++) {
        let nonce = 1;
        while (true) {
            const candidateInput = `${nonce}, ${currentHash}`;
            const candidateHash = sha256(candidateInput);
            const score = evalHashScore(candidateHash);

            if (score >= targetThreshold) {
                answers.push(nonce);
                currentHash = candidateHash;
                break;
            }
            nonce++;
        }
    }
    return answers;
}

function generateCdPayload() {
    const taskId = crypto.randomBytes(16).toString('hex');
    const now = Date.now();
    
    // Эмулируем время старта и отклика
    const st = now - Math.floor(Math.random() * 20) - 10;
    const rst = st - Math.floor(Math.random() * 40000) - 10000;
    const workTime = now;

    const startTime = process.hrtime.bigint();
    
    // ИСПРАВЛЕНО: передаем workTime (Date.now()), чтобы ответы решались под ТАЙМСТАМП!
    const answers = solveKasadaPow(taskId, 10, 2, workTime); 
    
    const endTime = process.hrtime.bigint();

    // Длительность в миллисекундах
    const actualDuration = Number(endTime - startTime) / 1e6; 
    const duration = Math.round((actualDuration + 80 + Math.random() * 20) * 10) / 10;

    return JSON.stringify({
        workTime: workTime,               // Unix timestamp в мс (напр. 1785182783058)
        id: taskId,
        answers: answers,                 // Теперь answers 100% совпадают с workTime!
        duration: duration,               // Длительность в мс (напр. 100.2)
        d: -43317,                        // Численный стейт
        st: st,                           // Unix timestamp в мс
        rst: rst                          // Unix timestamp в мс
    });
}

function formatHeaders(headers) {
    const clean = {};
    for (const [key, value] of Object.entries(headers)) {
        if (value !== undefined && value !== null) {
            clean[key] = Array.isArray(value) ? String(value[0]) : String(value);
        }
    }
    return clean;
}

// Заголовки Client Hints, полностью совпадающие с Chrome 120 на Windows
const BROWSER_CLIENT_HINTS = {
    "sec-ch-ua": '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"'
};
/**
 * ЛОКАЛЬНЫЙ ЗАПРОС ТОКЕНА ARKOSE (БЕЗ сторонних сервисов и без оплаты)
 * Формирует отпечаток bda и получает оригинальный токен от client-api.arkoselabs.com
 */
async function requestArkoseTokenLocal() {
    log("⚡ [Arkose] Запрос токена через arkose-solver...");

    try {
        const solver = new Solver({
            // Обязательные параметры
            publicKey: "E4C9E7E0-EA15-4D90-A619-DCFCE97FA009",
            site: "https://www.twitch.tv",
            surl: "https://client-api.arkoselabs.com", // ← явно указываем хост Arkose

            // URL страницы, с которой нужно взять свежий data[blob]
            dataExchangeUrl: "https://www.twitch.tv/signup",

            // Важно: тот же User-Agent, что и в TLS-сессии
            userAgent: USER_AGENT,

            // Если вы используете прокси для tlsSession, обязательно передайте его и сюда
            // proxy: "http://user:pass@host:port"
        });

        const result = await solver.solve();
        log(`[Arkose] 🎉 УСПЕХ! Токен получен: ${result.token.substring(0, 35)}...`);
        return result.token;

    } catch (e) {
        log(`[Arkose Error]: ${e.message}`);
        return null;
    }
}

/**
 * ШАГ 1: /mfc
 */
async function step1_mfc(tlsSession) {
    log("⚡ [ШАГ 1/3] Запрос контекста /mfc...");
    const headers = formatHeaders({
        ...BROWSER_CLIENT_HINTS,
        "User-Agent": USER_AGENT,
        "Accept": "*/*",
        "Origin": "https://www.twitch.tv",
        "Sec-Fetch-Site": "cross-site",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Dest": "empty",
        "Referer": "https://www.twitch.tv/",
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "Accept-Language": "en-US,en;q=0.9",
        "Content-Type": "application/json",
        "x-kpsdk-v": CONFIG.kasadaVersion,
        "x-kpsdk-h": "01"
    });

    logHttp("Step 1 /mfc", "OUTGOING REQUEST", CONFIG.mfcUrl, headers, "");

    const response = await tlsSession.post(CONFIG.mfcUrl, { headers, body: "" });

    logHttp("Step 1 /mfc", `INCOMING RESPONSE (${response.status})`, CONFIG.mfcUrl, response.headers, response.body);

    const extracted = extractKasadaTokens(response.headers);
    log(`[Step 1 Извлечено] x-kpsdk-h: ${extracted.hToken || 'НЕТ'}`);
    log(`[Step 1 Извлечено] x-kpsdk-ct: ${extracted.ctToken || 'НЕТ'}`);

    if (!extracted.hToken) {
        throw new Error("Сервер не вернул x-kpsdk-h на шаге /mfc!");
    }

    return extracted;
}

/**
 * ШАГ 2: Запрос на GQL integrity с сохранением x-kpsdk-h и x-kpsdk-r
 */
async function step2_integrity(tlsSession, step1Tokens) {
    log("\n--- ШАГ 2/3: Запрос Integrity-токена через GQL ---");
    const cdPayload = generateCdPayload();
    const clientRequestId = crypto.randomBytes(16).toString('hex');

    const headersMap = {
        ...BROWSER_CLIENT_HINTS,
        "User-Agent": USER_AGENT,
        "Client-ID": CONFIG.clientId,
        "X-Device-Id": CONFIG.deviceId,
        "Client-Session-Id": CONFIG.sessionId,
        "Client-Version": CONFIG.clientVersion,
        "Client-Request-Id": clientRequestId,
        
        "Accept": "*/*",
        "Content-Type": "application/json",
        "x-kpsdk-v": CONFIG.kasadaVersion,
        "x-kpsdk-cd": cdPayload,
        "x-kpsdk-h": step1Tokens.hToken,

        "Origin": "https://www.twitch.tv",
        "Sec-Fetch-Site": "same-site",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Dest": "empty",
        "Referer": "https://www.twitch.tv/",
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "Accept-Language": "en-US,en;q=0.9,ru;q=0.8"
    };

    if (step1Tokens.ctToken) {
        headersMap["x-kpsdk-ct"] = step1Tokens.ctToken;
    }

    const formattedHeaders = formatHeaders(headersMap);
    const bodyStr = JSON.stringify({});

    logHttp("Step 2 Integrity", "OUTGOING REQUEST", CONFIG.integrityUrl, formattedHeaders, bodyStr);

    const response = await tlsSession.post(CONFIG.integrityUrl, {
        headers: formattedHeaders,
        body: bodyStr
    });

    logHttp("Step 2 Integrity", `INCOMING RESPONSE (${response.status})`, CONFIG.integrityUrl, response.headers, response.body);

    const step2Tokens = extractKasadaTokens(response.headers);
    const finalCt = step2Tokens.ctToken || step1Tokens.ctToken;

    if (finalCt) {
        log(`\n[Kasada] 🎉 ПОБЕДА! Получен x-kpsdk-ct: ${finalCt.substring(0, 30)}...`);
    } else {
        log(`\n[Kasada] ❌ x-kpsdk-ct всё еще отсутствует.`);
    }

    const data = JSON.parse(response.body);
    return {
        integrityToken: data.token,
        kpsdkCt: finalCt,
        kpsdkH: step2Tokens.hToken || step1Tokens.hToken,
        kpsdkR: step2Tokens.rToken || "1-AA",
        responseHeaders: response.headers
    };
}

/**
 * Вспомогательная функция регистронезависимого поиска заголовков
 */
function getHeaderCaseInsensitive(headers, name) {
    if (!headers) return null;
    const foundKey = Object.keys(headers).find(k => k.toLowerCase() === name.toLowerCase());
    return foundKey ? headers[foundKey] : null;
}

/**
 * ШАГ 3: Регистрация с исправленным JSON-телом и всеми заголовками Kasada
 */
async function step3_register(tlsSession, tokens) {
    log("\n--- ШАГ 3/3: Отправка запроса на регистрацию ---");

    const arkoseToken = await requestArkoseTokenLocal(tlsSession);

    const registerBody = {
        username: CONFIG.account.username,
        password: CONFIG.account.password,
        email: CONFIG.account.email,
        birthday: CONFIG.account.birthday,
        client_id: CONFIG.clientId,
        integrity_token: tokens.integrityToken,
        include_verification_code: true
    };

    if (arkoseToken) {
        registerBody.captcha = {
            token: arkoseToken
        };
    } else {
        log(`⚠️ [ВНИМАНИЕ]: arkoseToken отсутствует! Запрос уйдёт БЕЗ captcha.token, что вызовет error_code 5021.`);
    }

    let kpCookies = [];
    const step2ResponseHeaders = tokens.responseHeaders;
    const setCookieHeader = getHeaderCaseInsensitive(step2ResponseHeaders, 'set-cookie');

    if (setCookieHeader) {
        const rawCookies = Array.isArray(setCookieHeader) ? setCookieHeader : [setCookieHeader];
        for (const c of rawCookies) {
            const match = c.match(/(KP_UIDz[^\s;=]*=[^;]+)/i);
            if (match) {
                kpCookies.push(match[1]);
            }
        }
    }

    const cookieHeaderParts = [`x-kpsdk-ct=${tokens.kpsdkCt}`];
    if (kpCookies.length > 0) {
        cookieHeaderParts.push(...kpCookies);
    }
    const fullCookieString = cookieHeaderParts.join("; ");
    const registerCdPayload = generateCdPayload();

    const headersMap = formatHeaders({
        ...BROWSER_CLIENT_HINTS,
        "User-Agent": USER_AGENT,
        "Client-ID": CONFIG.clientId,
        "X-Device-Id": CONFIG.deviceId,
        "Client-Session-Id": CONFIG.sessionId,
        "Client-Version": CONFIG.clientVersion,
        "Content-Type": "application/json",
        "Accept": "*/*",
        "client-integrity": tokens.integrityToken,
        "x-kpsdk-v": CONFIG.kasadaVersion,
        "x-kpsdk-ct": tokens.kpsdkCt,
        "x-kpsdk-cd": registerCdPayload,
        "x-kpsdk-h": tokens.kpsdkH,
        "x-kpsdk-r": tokens.kpsdkR,
        "Origin": "https://www.twitch.tv",
        "Sec-Fetch-Site": "same-site",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Dest": "empty",
        "Referer": "https://www.twitch.tv/",
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "Accept-Language": "en-US,en;q=0.9,ru;q=0.8",
        "Cookie": fullCookieString
    });

    const bodyStr = JSON.stringify(registerBody);

    logHttp("Step 3 Register", "OUTGOING REQUEST", CONFIG.registerUrl, headersMap, bodyStr);

    const response = await tlsSession.post(CONFIG.registerUrl, {
        headers: headersMap,
        body: bodyStr
    });

    logHttp("Step 3 Register", `INCOMING RESPONSE (${response.status})`, CONFIG.registerUrl, response.headers, response.body);
}

async function main() {
    console.log("=".repeat(70));
    console.log(" DIAGNOSTIC PROTO: KASADA TOKEN & COOKIE PARSER");
    console.log("=".repeat(70));

    await initTLS();

    // Настраиваем точный порядок заголовков как у настоящей Chrome 120
    const tlsSession = new Session({
        clientIdentifier: ClientIdentifier.chrome_120,
        withCookieJar: true,
        timeout: 15000,
        headerOrder: [
            "content-length",
            "sec-ch-ua",
            "sec-ch-ua-mobile",
            "user-agent",
            "sec-ch-ua-platform",
            "content-type",
            "client-id",
            "client-session-id",
            "client-version",
            "client-request-id",
            "client-integrity",
            "x-device-id",
            "accept",
            "x-kpsdk-v",
            "x-kpsdk-cd",
            "x-kpsdk-h",
            "x-kpsdk-ct",
            "x-kpsdk-r",
            "origin",
            "sec-fetch-site",
            "sec-fetch-mode",
            "sec-fetch-dest",
            "referer",
            "accept-encoding",
            "accept-language",
            "cookie"
        ]
    });

    try {
        // 1. Получаем контекст Kasada
        const step1Tokens = await step1_mfc(tlsSession);
        
        // 2. Получаем Integrity токен и вытаскиваем x-kpsdk-ct из ответа
        const tokens = await step2_integrity(tlsSession, step1Tokens);
        
        // 3. Пробуем зарегистрироваться
        await step3_register(tlsSession, tokens);

    } catch (err) {
        log(`[Ошибка]: ${err.message}`);
    } finally {
        await destroyTLS();
    }
}

main();