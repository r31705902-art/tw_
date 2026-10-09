const crypto = require('crypto');
const https = require('https');

// ====================================================================
// KASADA v1.2 PURE NODE.JS TOKEN GENERATOR (WITH DETAILED LOGS)
// ====================================================================

const CONFIG = {
    host: 'k.twitchcdn.net',
    basePath: '/149e9513-01fa-4fb0-aad4-566afd725d1b/2d206a39-8ed7-437e-a3be-862e0f06eea3',
    version: 'j-1.2.522',
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

// 3. Солвер Proof-of-Work (PoW) из байткода VM
function solveKasadaPow(taskId, targetDifficulty = 10, rounds = 2, workTime = 42) {
    console.log(`   [PoW Solver] Старт вычисления PoW (Task ID: ${taskId}, Rounds: ${rounds})...`);
    let inputSeed = `tp-v2-input, ${workTime}, ${taskId}`;
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
                console.log(`   [PoW Solver] Раунд ${round + 1} пройден! Nonce: ${nonce}, Score: ${score.toFixed(2)}`);
                answers.push(nonce);
                currentHash = candidateHash;
                break;
            }
            nonce++;
        }
    }

    return answers;
}

// 4. Сборка JSON Payload x-kpsdk-cd
function generateCdPayload() {
    const taskId = crypto.randomBytes(16).toString('hex'); // 32-символьный random hex
    const workTime = Math.floor(Math.random() * 40) + 20;

    const startTime = process.hrtime.bigint();
    const answers = solveKasadaPow(taskId, 10, 2, workTime);
    const endTime = process.hrtime.bigint();

    const duration = Number(endTime - startTime) / 1e9; // секунды

    const payloadObj = {
        workTime: workTime,
        id: taskId,
        answers: answers,
        duration: Math.round(duration * 1000) / 1000,
        d: {},
        st: 0,
        rst: 0
    };

    console.log(`   [PoW Solver] Генерация x-kpsdk-cd завершена за ${payloadObj.duration} сек.`);
    return JSON.stringify(payloadObj);
}

// Универсальный HTTP метод с детальным логированием
function makeRequest(path, headers, postData = '') {
    return new Promise((resolve, reject) => {
        const fullUrl = `https://${CONFIG.host}${path}`;
        
        console.log(`\n==================================================`);
        console.log(`📡 [ПОДКЛЮЧЕНИЕ] POST ${fullUrl}`);
        console.log(`📤 Отправляемые Заголовки (Headers):`);
        console.dir(headers, { depth: null, colors: true });
        
        if (postData) {
            console.log(`📦 Отправляемое Тело (Body / x-kpsdk-cd):`);
            console.log(`   ${postData}`);
        }

        const options = {
            hostname: CONFIG.host,
            port: 443,
            path: path,
            method: 'POST',
            headers: {
                'User-Agent': CONFIG.userAgent,
                'Accept': '*/*',
                'Host': CONFIG.host,
                'Origin': 'https://www.twitch.tv',
                'Referer': 'https://www.twitch.tv/',
                ...headers
            }
        };

        const startTime = Date.now();
        const req = https.request(options, (res) => {
            let body = '';
            res.on('data', chunk => body += chunk);
            res.on('end', () => {
                const duration = Date.now() - startTime;
                console.log(`\n📥 [ОТВЕТ ПОЛУЧЕН] (${duration} ms)`);
                console.log(`   Статус код: ${res.statusCode} ${res.statusMessage}`);
                console.log(`📥 Заголовки ответа (Response Headers):`);
                console.dir(res.headers, { depth: null, colors: true });
                console.log(`📄 Тело ответа (Response Body):`);
                console.log(`   ${body || '(Пустое тело ответа)'}`);
                console.log(`==================================================\n`);

                resolve({
                    status: res.statusCode,
                    headers: res.headers,
                    body: body
                });
            });
        });

        req.on('error', err => {
            console.error(`❌ [ОШИБКА СЕТИ]: ${err.message}`);
            reject(err);
        });

        if (postData) req.write(postData);
        req.end();
    });
}

// Основной процесс получения x-kpsdk-ct
async function getKasadaToken() {
    console.log("\n⚡ [ШАГ 1/2] Запрос первичной конфигурации /mfc...");

    // Вызов 1: Получение начального контекста
    const step1 = await makeRequest(`${CONFIG.basePath}/mfc`, {
        'Content-Type': 'application/json',
        'x-kpsdk-v': CONFIG.version,
        'x-kpsdk-h': '01'
    });

    const cookies = step1.headers['set-cookie'] ? step1.headers['set-cookie'].join('; ') : '';
    const kpsdkH = step1.headers['x-kpsdk-h'] || '01';

    console.log("⚡ [ШАГ 2/2] Генерация PoW и отправка решения...");

    // Сборка PoW решения
    const cdPayload = generateCdPayload();

    // Вызов 2: Отправка решения PoW
    const step2 = await makeRequest(`${CONFIG.basePath}/mfc`, {
        'Content-Type': 'application/json',
        'x-kpsdk-v': CONFIG.version,
        'x-kpsdk-cd': cdPayload,
        'x-kpsdk-h': kpsdkH,
        'Cookie': cookies
    });

    // Извлекаем токен из заголовков ответа
    const ctToken = step2.headers['x-kpsdk-ct'] || step2.headers['X-Kpsdk-Ct'];

    return {
        ctToken: ctToken || null,
        cdPayload: cdPayload,
        cookies: cookies || step2.headers['set-cookie'] || 'Нет кук',
        status: step2.status,
        allHeaders: step2.headers
    };
}

// ЗАПУСК
(async () => {
    try {
        console.log("🚀 Запуск чистого Kasada Token Generator...");
        const result = await getKasadaToken();

        console.log("\n==================================================");
        console.log("🎉 =============== РЕЗУЛЬТАТ KASADA ===============");
        console.log("==================================================");
        
        if (result.ctToken) {
            console.log("✅ УСПЕШНО ПОЛУЧЕН KASADA TOKEN (x-kpsdk-ct):");
            console.log(`\x1b[32m${result.ctToken}\x1b[0m\n`);
        } else {
            console.log("⚠️ Токен 'x-kpsdk-ct' не найден в заголовках первого уровня.");
            console.log("   Возможно, токен был передан в куках или статусе ответа.\n");
        }

        console.log("🔑 Сгенерированный PoW Payload (x-kpsdk-cd):");
        console.log(`   ${result.cdPayload}\n`);

        console.log("🍪 Итоговые Cookies:");
        console.log(`   ${result.cookies}\n`);

        console.log("📊 HTTP Статус второго шага:", result.status);
        console.log("==================================================\n");

    } catch (e) {
        console.error("\n❌ Ошибка генерации Kasada токена:", e.message);
    }
})();
