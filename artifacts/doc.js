const crypto = require('crypto');
const https = require('https');

// ====================================================================
// KASADA v1.2 PURE NODE.JS GENERATOR & API CLIENT
// ====================================================================

const CONFIG = {
    host: 'k.twitchcdn.net',
    basePath: '/149e9513-01fa-4fb0-aad4-566afd725d1b/2d206a39-8ed7-437e-a3be-862e0f06eea3',
    version: 'j-1.2.522',
    // Обязательная константа epd из байткода Kasada (scope_282 / address 22684):
    epd: '7ae9906d03439b1173e98ddb9342a718a535ab115a7f27138cd183737d7f7afe',
    userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
};

// 1. Хеширование SHA-256
function sha256(str) {
    return crypto.createHash('sha256').update(str, 'utf8').digest('hex');
}

// 2. Формула подсчета сложности хеша Kasada
function evalHashScore(hashStr) {
    const val = parseInt(hashStr.substring(0, 13), 16);
    return Math.pow(2, 52) / (val + 1);
}

// 3. Точный PoW-солвер из байткода VM (scope_389)
function solveKasadaPow(taskId, targetDifficulty = 10, rounds = 2, workTime = 42, epd = CONFIG.epd) {
    let inputSeed = `tp-v2-input, ${workTime}, ${taskId}`;
    if (epd) {
        inputSeed += `, ${epd}`;
    }

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

// 4. Сборка JSON Payload x-kpsdk-cd с эмуляцией времени браузера
function generateCdPayload() {
    const taskId = crypto.randomBytes(16).toString('hex');
    const workTime = Math.floor(Math.random() * 30) + 30; // 30-60 ms

    const startTime = process.hrtime.bigint();
    const answers = solveKasadaPow(taskId, 10, 2, workTime);
    const endTime = process.hrtime.bigint();

    const actualDuration = Number(endTime - startTime) / 1e9;
    // Эмуляция задержки выполнения Worker в браузере (15-35 мс)
    const duration = Math.round((actualDuration + 0.02) * 1000) / 1000;

    const st = Math.floor(Math.random() * 100) + 50;
    const rst = st + Math.floor(Math.random() * 150) + 100;

    const payloadObj = {
        workTime: workTime,
        id: taskId,
        answers: answers,
        duration: duration,
        d: {},
        st: st,
        rst: rst
    };

    return JSON.stringify(payloadObj);
}

// Универсальная обертка над HTTPS
function httpRequest(urlStr, headers, postData = '') {
    return new Promise((resolve, reject) => {
        const url = new URL(urlStr);
        const options = {
            hostname: url.hostname,
            port: 443,
            path: url.pathname + url.search,
            method: 'POST',
            headers: {
                'User-Agent': CONFIG.userAgent,
                'Accept': '*/*',
                'Origin': 'https://www.twitch.tv',
                'Referer': 'https://www.twitch.tv/',
                ...headers
            }
        };

        console.log(`\n==================================================`);
        console.log(`📡 [ПОДКЛЮЧЕНИЕ] POST ${urlStr}`);
        console.log(`📤 Заголовки (Headers):`);
        console.dir(headers, { depth: null, colors: true });

        const req = https.request(options, (res) => {
            let body = '';
            res.on('data', chunk => body += chunk);
            res.on('end', () => {
                console.log(`\n📥 [ОТВЕТ ПОЛУЧЕН] ${res.statusCode} ${res.statusMessage}`);
                console.log(`📥 Ответные Заголовки (Response Headers):`);
                console.dir(res.headers, { depth: null, colors: true });
                console.log(`==================================================`);

                resolve({
                    status: res.statusCode,
                    headers: res.headers,
                    body: body
                });
            });
        });

        req.on('error', err => reject(err));
        if (postData) req.write(postData);
        req.end();
    });
}

// Главный цикл получения CT
async function getKasadaClientToken() {
    // -------------------------------------------------------------
    // ШАГ 1: Инициализация контекста сессии (/mfc)
    // -------------------------------------------------------------
    console.log("⚡ [ШАГ 1/3] Запрос сессионного хэша через /mfc...");
    const step1Url = `https://${CONFIG.host}${CONFIG.basePath}/mfc`;
    
    const step1 = await httpRequest(step1Url, {
        'Content-Type': 'application/json',
        'x-kpsdk-v': CONFIG.version,
        'x-kpsdk-h': '01'
    });

    const kpsdkH = step1.headers['x-kpsdk-h'];
    if (!kpsdkH) {
        throw new Error("Сервер не вернул заголовок x-kpsdk-h на шаге 1.");
    }
    console.log(`✅ Получен сессионный контекст x-kpsdk-h: ${kpsdkH}`);

    // -------------------------------------------------------------
    // ШАГ 2: Генерация PoW решения (x-kpsdk-cd)
    // -------------------------------------------------------------
    console.log("\n⚡ [ШАГ 2/3] Локальная генерация PoW (x-kpsdk-cd)...");
    const cdPayload = generateCdPayload();
    console.log(`🔑 Сгенерированный PoW Payload: ${cdPayload}`);

    // -------------------------------------------------------------
    // ШАГ 3: Запрос к защищенному API Twitch (где Kasada выдает x-kpsdk-ct)
    // -------------------------------------------------------------
    console.log("\n⚡ [ШАГ 3/3] Отправка PoW вместе с запросом к API Twitch (gql.twitch.tv)...");
    
    const targetApiUrl = "https://gql.twitch.tv/gql";

    // Стандартный GraphQL payload Twitch (запрос токена плеера)
    const gqlPayload = JSON.stringify([{
        operationName: "PlaybackAccessToken",
        variables: {
            isLive: true,
            login: "twitch",
            isVod: false,
            vodID: "",
            playerType: "embed"
        },
        extensions: {
            persistedQuery: {
                version: 1,
                sha256Hash: "08282203846d3e54019a8a2916e389c998450e1b8a0773d910e8239213520625"
            }
        }
    }]);

    const step3 = await httpRequest(targetApiUrl, {
        'Content-Type': 'application/json',
        'Client-Id': 'kimne78kx3ncx6br8h4mv6wki5h1ko',
        'x-kpsdk-v': CONFIG.version,
        'x-kpsdk-h': kpsdkH,
        'x-kpsdk-cd': cdPayload
    }, gqlPayload);

    // Извлекаем токен x-kpsdk-ct из ответа API
    const ctToken = step3.headers['x-kpsdk-ct'] || step3.headers['X-Kpsdk-Ct'];
    const cookies = step3.headers['set-cookie'];

    return {
        ctToken: ctToken || null,
        cookies: cookies || null,
        status: step3.status
    };
}

// ЗАПУСК
(async () => {
    try {
        console.log("🚀 Запуск точного генератора Kasada v1.2...");
        const res = await getKasadaClientToken();

        console.log("\n==================================================");
        if (res.ctToken) {
            console.log("🎉 ✅ УСПЕШНО ПОЛУЧЕН KASADA CLIENT TOKEN (x-kpsdk-ct):");
            console.log(`\x1b[32m${res.ctToken}\x1b[0m\n`);
        } else {
            console.log("⚠️ Токен x-kpsdk-ct не найден в заголовках первого уровня.");
            if (res.cookies) {
                console.log("🍪 Проверьте Set-Cookie:", res.cookies);
            }
        }
        console.log("==================================================");
    } catch (e) {
        console.error("❌ Ошибка:", e.message);
    }
})();