// prot.js — Диагностический скрипт с проверкой UDMUX и Direct RakNet
const dgram = require('dgram');
const crypto = require('crypto');
const https = require('https');
const fs = require('fs');
const path = require('path');

const PLACE_ID = 5534891288;
let ROBLOSECURITY = process.env.ROBLOSECURITY || '';

if (!ROBLOSECURITY) {
    const cookiePath = path.join(__dirname, 'cookie.txt');
    if (fs.existsSync(cookiePath)) ROBLOSECURITY = fs.readFileSync(cookiePath, 'utf8').trim();
}

const RAKNET_MAGIC = Buffer.from([
    0x00, 0xff, 0xff, 0x00, 0xfe, 0xfe, 0xfe, 0xfe,
    0xfd, 0xfd, 0xfd, 0xfd, 0x12, 0x34, 0x56, 0x78
]);

function log(...args) {
    const t = new Date().toISOString().substr(11, 12);
    console.log(`[${t}]`, ...args);
}

function request(method, url, headers = {}, body = null) {
    return new Promise((resolve, reject) => {
        const u = new URL(url);
        const opts = {
            method,
            hostname: u.hostname,
            path: u.pathname + u.search,
            headers: {
                'User-Agent': 'Roblox/WinInet',
                'Accept': 'application/json',
                'Content-Type': 'application/json',
                'Origin': 'https://www.roblox.com',
                'Referer': 'https://www.roblox.com/',
                'Cookie': `.ROBLOSECURITY=${ROBLOSECURITY}`,
                ...headers
            }
        };

        const req = https.request(opts, res => {
            let data = '';
            res.on('data', c => data += c);
            res.on('end', () => {
                let parsed = data;
                try { parsed = JSON.parse(data); } catch {}
                resolve({ status: res.statusCode, headers: res.headers, body: parsed, raw: data });
            });
        });
        req.on('error', reject);
        if (body) req.write(typeof body === 'string' ? body : JSON.stringify(body));
        req.end();
    });
}

function buildUdmuxHeader(internalIP, internalPort, tokenValue, pepperId) {
    const header = Buffer.alloc(32);
    header[0] = 0x01; header[1] = 0x00; header[2] = 0x00; header[3] = 0x1f; header[4] = 0x01; header[5] = 0x11;
    header[6] = 0x01;

    let tokenBuf;
    try { tokenBuf = Buffer.from(tokenValue || '', 'base64'); } catch { tokenBuf = Buffer.alloc(16); }
    tokenBuf.copy(header, 7, 0, Math.min(16, tokenBuf.length));

    const ipParts = (internalIP || '10.0.0.1').split('.').map(Number);
    header[23] = ipParts[3] & 0xff;
    header[24] = ipParts[2] & 0xff;
    header[25] = ipParts[0] & 0xff;
    header[26] = ipParts[1] & 0xff;

    header.writeUInt16BE(internalPort || 0, 27);

    const pepper = pepperId || 0;
    header[29] = (pepper >> 16) & 0xff;
    header[30] = (pepper >> 8) & 0xff;
    header[31] = pepper & 0xff;

    return header;
}

function buildOpenConnectionRequest1() {
    const raknet = Buffer.alloc(1168);
    RAKNET_MAGIC.copy(raknet, 0);
    raknet[16] = 0x05;
    raknet[17] = 0x01;
    return raknet;
}

async function doHttpJoin() {
    log('=== 1. Проверка авторизации ===');
    const auth = await request('GET', 'https://users.roblox.com/v1/users/authenticated');
    if (auth.status !== 200) throw new Error('Не авторизован');
    log(`OK → ${auth.body.name}`);

    log('=== 2. CSRF ===');
    const logout = await request('POST', 'https://auth.roblox.com/v2/logout');
    const csrf = logout.headers['x-csrf-token'];
    if (!csrf) throw new Error('Нет CSRF');

    log('=== 3. join-game ===');
    const join = await request('POST', 'https://gamejoin.roblox.com/v1/join-game', {
        'X-CSRF-TOKEN': csrf,
        'Referer': `https://www.roblox.com/games/${PLACE_ID}/`
    }, { placeId: PLACE_ID, isTeleport: false, gameJoinAttemptId: crypto.randomUUID() });

    if (join.status !== 200 || !join.body?.joinScript) throw new Error('join-game failed');

    const js = join.body.joinScript;
    let udmuxIP = js.UdmuxEndpoints?.[0]?.Address || js.ServerConnections?.[0]?.Address;
    let udmuxPort = js.UdmuxEndpoints?.[0]?.Port || js.ServerConnections?.[0]?.Port;

    log(`Udmux Target: ${udmuxIP}:${udmuxPort}`);
    log(`MachineAddress: ${js.MachineAddress}:${js.ServerPort}`);

    return {
        udmuxIP, udmuxPort,
        tokenValue: js.TokenValue,
        pepperId: js.PepperId,
        internalIP: js.MachineAddress,
        internalPort: js.ServerPort
    };
}

function tryUdpProbe(data) {
    const { udmuxIP, udmuxPort, tokenValue, pepperId, internalIP, internalPort } = data;

    const socket = dgram.createSocket('udp4');

    socket.on('message', (msg, rinfo) => {
        log(`\n🎉 ← ПОЛУЧЕН ОТВЕТ! ${msg.length} байт от ${rinfo.address}:${rinfo.port}`);
        log(`HEX: ${msg.toString('hex')}\n`);
        process.exit(0);
    });

    socket.on('error', e => log('UDP error:', e.message));

    socket.bind(0, () => {
        const address = socket.address();
        log(`Локальный сокет привязан к порту: ${address.port}`);
        log(`ВАЖНО: Если ответа нет, проверьте, что порт ${address.port} не заблокирован Брандмауэром Windows.`);

        const udmuxHeader = buildUdmuxHeader(internalIP, internalPort, tokenValue, pepperId);
        const raknetPayload = buildOpenConnectionRequest1();
        const udmuxPacket = Buffer.concat([udmuxHeader, raknetPayload]); // 1200B

        // Чистый RakNet без UDMUX
        const rawRaknetPacket = Buffer.concat([RAKNET_MAGIC, Buffer.from([0x05, 0x01]), Buffer.alloc(1182)]); // 1200B

        let count = 0;
        const sendInterval = setInterval(() => {
            count++;
            // Отправляем вариант с UDMUX
            socket.send(udmuxPacket, udmuxPort, udmuxIP, () => {
                log(`→ [#${count}] Отправил UDMUX+0x05 (1200B) на ${udmuxIP}:${udmuxPort}`);
            });
            // Отправляем вариант без UDMUX (на случай Direct Return)
            socket.send(rawRaknetPacket, udmuxPort, udmuxIP, () => {
                log(`→ [#${count}] Отправил RAW RakNet 0x05 (1200B) на ${udmuxIP}:${udmuxPort}`);
            });

            if (count >= 5) clearInterval(sendInterval);
        }, 1000);
    });

    setTimeout(() => {
        log('Таймаут.');
        socket.close();
        process.exit(0);
    }, 8000);
}

(async () => {
    try {
        const data = await doHttpJoin();
        tryUdpProbe(data);
    } catch (e) {
        log('ОШИБКА:', e.message);
    }
})();