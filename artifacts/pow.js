// ----------------------------------------------------------------------------
// 1. Битовые функции SHA-256 (ROTR, sigma0, sigma1, Sigma0, Sigma1, Ch, Maj)
// ----------------------------------------------------------------------------

function rotr(x, n) {
    return (x >>> n) | (x << (32 - n));
}

/* PC 17637 - PC 17685 */
function sigma0(x) {
    // ROTR^7(x) ^ ROTR^18(x) ^ (x >>> 3)
    return rotr(x, 7) ^ rotr(x, 18) ^ (x >>> 3);
}

/* PC 17708 - PC 17756 */
function sigma1(x) {
    // ROTR^17(x) ^ ROTR^19(x) ^ (x >>> 10)
    return rotr(x, 17) ^ rotr(x, 19) ^ (x >>> 10);
}

/* PC 18000 - PC 18047 */
function Sigma0(x) {
    // ROTR^2(x) ^ ROTR^13(x) ^ ROTR^22(x)
    return rotr(x, 2) ^ rotr(x, 13) ^ rotr(x, 22);
}

/* PC 18050 - PC 18108 */
function Sigma1(x) {
    // ROTR^6(x) ^ ROTR^11(x) ^ ROTR^25(x)
    return rotr(x, 6) ^ rotr(x, 11) ^ rotr(x, 25);
}

/* PC 18155 - PC 18182 */
function Ch(x, y, z) {
    return (x & y) ^ (~x & z);
}

/* PC 18115 - PC 18148 */
function Maj(x, y, z) {
    return (x & y) ^ (x & z) ^ (y & z);
}


// ----------------------------------------------------------------------------
// 2. Инициализация констант SHA-256 Engine
// ----------------------------------------------------------------------------

/* PC 12005 - PC 12073 */
const INITIAL_H = new Uint32Array([
    1779033703, // H0 = 0x6A09E667
    3144134277, // H1 = 0xBB67AE85
    1013904242, // H2 = 0x3C6EF372
    2773480762, // H3 = 0xA54FF53A
    1359893119, // H4 = 0x510E527F
    2600822924, // H5 = 0x9B05688C
    528734635,  // H6 = 0x1F83D9AB
    1541459225  // H7 = 0x5BE0CD19
]);

/* PC 13614 - PC 13963 */
const K_CONSTANTS = new Uint32Array([
    1116352408, 1899447441, 3049323471, 3921009573, 961987163,  1508970993, 2453635748, 2870763221,
    3624381080, 310598401,  607225278,  1426881987, 1925078388, 2162078206, 2614888103, 3248222580,
    3835390401, 4022224774, 264347078,  604807628,  770255983,  1249150122, 1555081692, 1996064986,
    2554220882, 2821834349, 2952996808, 3210313671, 3336571891, 3584528711, 113926993,  338241895,
    666307205,  773529912,  1294757372, 1396182291, 1695183700, 1986661051, 2177026350, 2456956037,
    2730485921, 2820302411, 3259730800, 3345764771, 3516065817, 3600352804, 4094571909, 275423344,
    430227734,  506948616,  659060556,  883997877,  958139571,  1322822218, 1537002063, 1747873779,
    1955562222, 2024104815, 2227730452, 2361852424, 2428436474, 2756734187, 3204031479, 3329325298
]);


// ----------------------------------------------------------------------------
// 3. Функция внутреннего хеширования блока (VM SHA-256 Routine)
// ----------------------------------------------------------------------------

/* PC 17604 - PC 19428 */
function compute_vm_sha256(inputData) {
    let W = new Uint32Array(64);
    
    // Подготовка сообщений W[0..15]
    for (let i = 0; i < 16; i++) {
        W[i] = inputData[i] || 0;
    }

    // Расширение расписания сообщений W[16..63]
    /* PC 17607 */
    for (let t = 16; t < 64; t++) {
        /* PC 17627 */ let s0 = sigma0(W[t - 15]);
        /* PC 17698 */ let s1 = sigma1(W[t - 2]);
        /* PC 17811 */ W[t] = (W[t - 16] + s0 + W[t - 7] + s1) | 0;
    }

    // Инициализация рабочих переменных a..h
    let a = INITIAL_H[0], b = INITIAL_H[1], c = INITIAL_H[2], d = INITIAL_H[3];
    let e = INITIAL_H[4], f = INITIAL_H[5], g = INITIAL_H[6], h = INITIAL_H[7];

    // 64 раунда сжатия
    /* PC 17847 */
    for (let i = 0; i < 64; i++) {
        /* PC 18047 */ let S1 = Sigma1(e);
        /* PC 18182 */ let ch = Ch(e, f, g);
        /* PC 18226 */ let temp1 = (h + S1 + ch + K_CONSTANTS[i] + W[i]) | 0;

        /* PC 18047 */ let S0 = Sigma0(a);
        /* PC 18152 */ let maj = Maj(a, b, c);
        /* PC 18243 */ let temp2 = (S0 + maj) | 0;

        h = g;
        g = f;
        f = e;
        e = (d + temp1) | 0;
        d = c;
        c = b;
        b = a;
        a = (temp1 + temp2) | 0;
    }

    return (a >>> 0); // Возвращаем старшую часть хэша для оценки сложности
}


// ----------------------------------------------------------------------------
// 4. Главный цикл перебора Nonce и решение PoW (Nonce Loop)
// ----------------------------------------------------------------------------

/**
 * Основная логика генерации PoW задачи Kasada.
 * @param {string} challengeSeed - Соль/челлендж от сервера (x-kpsdk-cd)
 * @param {number} targetDifficulty - Порог требуемой сложности
 * @param {number} maxIterations - Максимальное кол-во циклов
 */
function solve_kasada_pow(challengeSeed, targetDifficulty, maxIterations) {
    /* PC 10356 */ let startTime = Date.now();
    /* PC 10044 */ let answers = [];
    
    /* PC 10049 */
    for (let i = 0; i < maxIterations; i++) {
        /* PC 10065 */ let nonce = 1;
        
        while (true) {
            /* PC 10094 */ let candidateStr = challengeSeed + nonce;
            
            // Расчет хэша текущего кандидата
            /* PC 10159 */ let hashScore = compute_vm_sha256(candidateStr);
            
            /* PC 10166 */ 
            if (hashScore >= targetDifficulty) {
                // Найдено решение, удовлетворяющее сложности!
                /* PC 10185 */ answers.push(nonce);
                /* PC 10205 */ break; // Переход к следующей подзадаче
            }

            /* PC 10217 */ nonce++;
        }
    }

    /* PC 10380 */ let endTime = Date.now();
    /* PC 10427 */ let workTimeMs = (endTime - startTime) * 1000;

    /* PC 10449 - PC 10508 */
    let powPayload = {
        "workTime": workTimeMs,      // Время вычислений
        "st": startTime,             // Timestamp начала
        "answers": answers,          // Найденные значения Nonce
        "rst": performance.now()     // Монотонное время загрузки
    };

    /* PC 10514 */
    return powPayload;
}

// ============================================================================
// 5: Объединение PoW и DOM-телеметрии (gjn, qkx, gzw) в единый Payload
// ============================================================================
// Описание: Kasada бракует токены (выдает ошибку 5025), если PoW
// отправляется "всухую" без телеметрии. Ниже показан фрагмент байт-кода, 
// где в итоговый объект подмешиваются массивы пользовательских событий.

function assemble_full_interrogation_payload(powMetrics, telemetryData) {
    /* PC 10449 - PC 10487 */
    let fullPayload = {
        // --- 1. Метрики решения задачи (PoW) ---
        "workTime": powMetrics.workTime, // Время выполнения в мс
        "st": powMetrics.st,             // Timestamp старта
        "answers": powMetrics.answers,   // Массив ответов Nonce
        "rst": powMetrics.rst,           // Монотонный таймер загрузки

        // --- 2. Телеметрия DOM и пользовательского ввода ---
        /* PC 23081 */ "gjn": telemetryData.gjn || [], // История событий (mousemove, keydown)
        /* PC 37333 */ "qkx": telemetryData.qkx || [], // Дельты координат (ΔX, ΔY, Δt)
        /* PC 38432 */ "gzw": 1610                      // Конфигурационный код задержек
    };

    return fullPayload;
}


// ============================================================================
// 6: Алгоритм сериализации и шифрования заголовка x-kpsdk-cd
// ============================================================================
// Описание: Объект с PoW и телеметрией не передается в открытом виде.
// В VM выполняется 3-этапная конвейерная обработка:
// 1. JSON.stringify() объекта
// 2. XOR-маскирование байт с динамическим ключом
// 3. Кодирование в Base64 с кастомной таблицей символов

/**
 * Кодирование готового Payload в итоговую строку x-kpsdk-cd.
 * @param {Object} payloadObj - Полный объект с PoW и gjn/qkx телеметрией
 * @param {Uint8Array} dynamicSessionKey - Динамический ключ интеррогации
 * @param {string} customBase64Alphabet - Кастомный алфавит Base64
 */
function encode_kpsdk_cd_header(payloadObj, dynamicSessionKey, customBase64Alphabet) {
    // Шаг 1: Сериализация объекта в JSON-строку
    let jsonString = JSON.stringify(payloadObj);
    
    // Шаг 2: Маскирование байт через XOR с динамическим ключом
    let maskedBytes = new Uint8Array(jsonString.length);
    for (let i = 0; i < jsonString.length; i++) {
        let charCode = jsonString.charCodeAt(i);
        let keyByte = dynamicSessionKey[i % dynamicSessionKey.length];
        
        /* PC 13068 */ let padOuter = 92; // 0x5C
        /* PC 13085 */ let padInner = 54; // 0x36
        
        // Применение XOR маски
        maskedBytes[i] = charCode ^ keyByte ^ padInner;
    }

    // Шаг 3: Кодирование массива байт кастомной базой Base64
    let finalString = "";
    for (let i = 0; i < maskedBytes.length; i += 3) {
        let b1 = maskedBytes[i];
        let b2 = i + 1 < maskedBytes.length ? maskedBytes[i + 1] : 0;
        let b3 = i + 2 < maskedBytes.length ? maskedBytes[i + 2] : 0;

        let triplet = (b1 << 16) | (b2 << 8) | b3;

        // Кодирование с использованием кастомной таблицы символов
        finalString += customBase64Alphabet[(triplet >> 18) & 63];
        finalString += customBase64Alphabet[(triplet >> 12) & 63];
        finalString += (i + 1 < maskedBytes.length) ? customBase64Alphabet[(triplet >> 6) & 63] : "=";
        finalString += (i + 2 < maskedBytes.length) ? customBase64Alphabet[triplet & 63] : "=";
    }

    // Итоговое значение, отправляемое в HTTP-заголовке x-kpsdk-cd
    return finalString;
}