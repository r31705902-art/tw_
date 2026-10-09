'use strict';
// Registration pipeline. Each stage returns a structured result and never
// throws; the caller decides what to retry. Every request goes through the
// proxy pool so tiers can be swapped at runtime.
const https = require('https');
const http = require('http');
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const { URL } = require('url');

const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36';
const CLIENT_ID = 'kimne78kx3ncx6brgo4mv6wki5h1ko';
const CLIENT_VERSION = 'b3c382ac-5d5d-4d76-98f2-b05bbd59bf18';
const KASADA_VERSION = 'j-1.2.522';
const MFC = 'https://k.twitchcdn.net/149e9513-01fa-4fb0-aad4-566afd725d1b/2d206a39-8ed7-437e-a3be-862e0f06eea3/mfc';
const GQL = 'https://gql.twitch.tv/integrity';
const REGISTER = 'https://passport.twitch.tv/protected_register';
const ARKOSE_PK = 'E5558E2B-4C90-4A61-8608-542B28B31580';
const AK_URL = 'https://client-api.arkoselabs.com';
const EPD = '7ae9906d03439b1173e98ddb9342a718a535ab115a7f27138cd183737d7f7afe';

// optional TLS impersonation; falls back to plain https when absent
let tls = null;
try { tls = require('node-tls-client'); } catch (e) { tls = null; }

const TlsReady = { inited: false };

const secCh = {
  'sec-ch-ua': '"Chromium";v="152", "Not;A=Brand";v="24"',
  'sec-ch-ua-mobile': '?0',
  'sec-ch-ua-platform': '"Windows"',
};

function randHex(n) { return crypto.randomBytes(n).toString('hex'); }
function sha256hex(s) { return crypto.createHash('sha256').update(s, 'utf8').digest('hex'); }
function score(h) { return Math.pow(2, 52) / (parseInt(h.slice(0, 13), 16) + 1); }

function solvePow(taskId, workTime) {
  let cur = sha256hex(`tp-v2-input, ${workTime}, ${taskId}, ${EPD}`);
  const answers = [];
  const target = 5;
  for (let r = 0; r < 2; r++) {
    let n = 1;
    while (score(sha256hex(`${n}, ${cur}`)) < target) n++;
    answers.push(n);
    cur = sha256hex(`${n}, ${cur}`);
  }
  return answers;
}

function buildCd() {
  const id = randHex(16);
  const now = Date.now();
  return JSON.stringify({
    workTime: now, id, answers: solvePow(id, now),
    duration: 92.4, d: -43317, st: now - 12, rst: now - 33000,
  });
}

// ---- transport ------------------------------------------------------------
async function request(method, url, { headers = {}, body = null, proxy = null, timeoutMs = 30000 }) {
  const u = new URL(url);
  const payload = body === null ? null : (typeof body === 'string' ? body : JSON.stringify(body));
  const opts = {
    protocol: u.protocol, hostname: u.hostname, port: u.port || 443, method,
    path: u.pathname + u.search,
    headers: { ...secCh, 'user-agent': UA, accept: '*/*', ...headers },
    timeout: timeoutMs,
  };

  if (payload !== null) {
    opts.headers['content-length'] = String(Buffer.byteLength(payload));
    opts.headers['content-type'] = opts.headers['content-type'] || 'application/json';
  }

  if (proxy && proxy.url && tls) {
    // node-tls-client v2: initTLS/destroyTLS are process-wide teardown hooks
    if (tls.initTLS && !TlsReady.inited) {
      await tls.initTLS().catch(() => { });
      TlsReady.inited = true;
    }
    const session = new tls.Session({ clientIdentifier: 'chrome_131', timeout: timeoutMs, withCookieJar: true, proxy: proxy.url });
    const close = (session.close && session.close.bind(session)) || (tls.destroyTLS && tls.destroyTLS.bind(tls));
    try {
      const r = method === 'GET'
        ? await session.get(url, { headers: opts.headers })
        : await session.post(url, { headers: opts.headers, body: payload || undefined });
      const text = await r.text();
      return { status: r.status, headers: r.headers || {}, body: text };
    } finally { if (close) close().catch(() => { }); }
  }

  const client = u.protocol === 'https:' ? https : http;
  return new Promise((resolve, reject) => {
    const req = client.request(opts, res => {
      let data = '';
      res.setEncoding('utf8');
      res.on('data', c => data += c);
      res.on('end', () => resolve({ status: res.statusCode, headers: res.headers, body: data }));
    });
    req.on('timeout', () => { req.destroy(new Error('request timeout')); });
    req.on('error', reject);
    if (payload !== null) req.write(payload);
    req.end();
  });
}

function headerAny(headers, name) {
  if (!headers) return null;
  const k = Object.keys(headers).find(h => h.toLowerCase() === name.toLowerCase());
  if (!k) return null;
  const v = headers[k];
  return Array.isArray(v) ? v[0] : v;
}

// ---- stages ---------------------------------------------------------------
async function mfc(proxy) {
  const r = await request('POST', MFC, {
    headers: {
      origin: 'https://www.twitch.tv', referer: 'https://www.twitch.tv/',
      'sec-fetch-site': 'cross-site', 'sec-fetch-mode': 'cors', 'sec-fetch-dest': 'empty',
      'content-type': 'application/json',
      'x-kpsdk-v': KASADA_VERSION, 'x-kpsdk-h': '01',
    },
    body: '', proxy,
  });
  const h = headerAny(r.headers, 'x-kpsdk-h');
  if (r.status !== 200 || !h) return { ok: false, stage: 'mfc', status: r.status, error: `no x-kpsdk-h (${r.status})`, body: r.body.slice(0, 200) };
  return { ok: true, stage: 'mfc', h };
}

async function integrity(hToken, proxy) {
  const deviceId = randHex(16);
  const sessionId = randHex(16);
  const r = await request('POST', GQL, {
    headers: {
      'client-id': CLIENT_ID, 'x-device-id': deviceId,
      'client-session-id': sessionId, 'client-version': CLIENT_VERSION,
      'client-request-id': randHex(16),
      'content-type': 'application/json',
      'x-kpsdk-v': KASADA_VERSION, 'x-kpsdk-cd': buildCd(), 'x-kpsdk-h': hToken,
      origin: 'https://www.twitch.tv', referer: 'https://www.twitch.tv/',
      'sec-fetch-site': 'same-site', 'sec-fetch-mode': 'cors', 'sec-fetch-dest': 'empty',
    },
    body: '{}', proxy,
  });
  let json = {};
  try { json = JSON.parse(r.body); } catch (e) { }
  const ct = headerAny(r.headers, 'x-kpsdk-ct');
  if (r.status !== 200 || !json.token) {
    return { ok: false, stage: 'integrity', status: r.status, error: `no token (${r.status})`, body: r.body.slice(0, 200) };
  }
  return { ok: true, stage: 'integrity', token: json.token, ct, deviceId, sessionId };
}

// arkose token. Order matters: cheapest first, browser last.
async function arkose(proxy, opts = {}) {
  // 1) native solver with the key extracted from the enforcement bundle
  const fromSolver = await trySolver(proxy);
  if (fromSolver.ok) return fromSolver;
  // 2) browser-captured token, if one was left on disk
  const cached = tryCachedToken();
  if (cached.ok) return cached;
  // 3) fresh browser capture, only when explicitly allowed
  if (opts.browser) {
    const captured = await tryBrowserCapture(opts);
    if (captured.ok) return captured;
  }
  return { ok: false, stage: 'arkose', error: 'no token source produced a token', attempts: [fromSolver, cached] };
}

function tryCachedToken() {
  const p = path.join(__dirname, 'token.txt');
  if (!fs.existsSync(p)) return { ok: false, stage: 'arkose-cache', error: 'no cached token' };
  const token = fs.readFileSync(p, 'utf8').trim();
  return { ok: true, stage: 'arkose-cache', token };
}

async function trySolver(proxy) {
  try {
    const { extractRsaKey, generateBda, newSession, encrypt, marshalBda } = require('./arkose');
    const api = await request('GET', `${AK_URL}/v2/${ARKOSE_PK}/api.js`, { headers: { 'user-agent': UA }, proxy });
    const key = extractRsaKey(api.body);
    if (!key) return { ok: false, stage: 'arkose-solver', error: 'no RSA key in api.js (key rotated to enforcement bundle)' };
    const bda = generateBda({ surl: `${AK_URL}/vc`, language: 'en-US', title: '', enforcementHash: '6d0c4af962acb40222b82fccf3418258' }, '');
    const enc = encrypt(marshalBda(bda), key);
    const form = new URLSearchParams({
      bda: enc, public_key: ARKOSE_PK, site: 'https://www.twitch.tv',
      userbrowser: UA, capi_version: '2.18.1', capi_mode: 'lightbox',
      style_theme: 'default', rnd: String(Math.random()), language: 'en-US',
    });
    const r = await request('POST', `${AK_URL}/fc/gt2/public_key/${ARKOSE_PK}`, {
      headers: { 'content-type': 'application/x-www-form-urlencoded; charset=UTF-8', origin: 'https://www.twitch.tv', referer: 'https://www.twitch.tv/' },
      body: form.toString(), proxy,
    });
    const json = JSON.parse(r.body);
    const token = json.token || (json.body && JSON.parse(json.body).token);
    if (token) return { ok: true, stage: 'arkose-solver', token };
    return { ok: false, stage: 'arkose-solver', error: `gt2: ${r.body.slice(0, 120)}` };
  } catch (e) {
    return { ok: false, stage: 'arkose-solver', error: e.message };
  }
}

async function tryBrowserCapture(opts = {}) {
  // camoufox/puppeteer is optional and heavy; only used when asked for
  try {
    const which = opts.browser === 'camoufox' ? 'camoufox' : 'puppeteer';
    const runner = require(which === 'camoufox' ? './browser-camoufox' : './browser-puppeteer');
    const token = await runner.capture({ proxy: opts.proxy });
    if (token) { fs.writeFileSync(path.join(__dirname, 'token.txt'), token); return { ok: true, stage: 'browser', token }; }
    return { ok: false, stage: 'browser', error: 'capture returned nothing' };
  } catch (e) {
    return { ok: false, stage: 'browser', error: e.message };
  }
}

// ---- register -------------------------------------------------------------
function newAccount() {
  const s = Date.now().toString(36).slice(-6);
  return {
    username: 'user' + s,
    password: 'Sup3r' + s + '!x',
    email: `user${s}@outlook.com`,
    birthday: { day: 15, month: 5, year: 1998 },
  };
}

async function register(pool, opts = {}) {
  const account = opts.account || newAccount();
  const result = { account, stages: [] };
  const useProxy = () => pool.current();

  let proxy = useProxy();
  const m = await mfc(proxy);
  result.stages.push(m);
  if (!m.ok) return { ...result, ok: false, error: `mfc: ${m.error}` };

  const i = await integrity(m.h, proxy);
  result.stages.push(i);
  if (!i.ok) return { ...result, ok: false, error: `integrity: ${i.error}` };

  const a = await arkose(proxy, opts);
  result.stages.push(a);
  if (!a.ok) return { ...result, ok: false, error: `arkose: ${a.error}` };

  const body = {
    username: account.username,
    password: account.password,
    email: account.email,
    birthday: account.birthday,
    client_id: CLIENT_ID,
    integrity_token: i.token,
    captcha: { token: a.token },
  };

  const r = await request('POST', REGISTER, {
    headers: {
      ...secCh, 'user-agent': UA, 'client-id': CLIENT_ID,
      'x-device-id': i.deviceId, 'client-session-id': i.sessionId,
      'client-version': CLIENT_VERSION, 'client-integrity': i.token,
      'content-type': 'application/json',
      origin: 'https://www.twitch.tv', referer: 'https://www.twitch.tv/',
      'x-kpsdk-v': KASADA_VERSION, 'x-kpsdk-ct': i.ct || '', 'x-kpsdk-cd': buildCd(),
      'x-kpsdk-h': m.h, 'x-kpsdk-r': '1-AA',
      cookie: `x-kpsdk-ct=${i.ct || ''}`,
    },
    body, proxy,
  });
  let json = {};
  try { json = JSON.parse(r.body); } catch (e) { }
  result.stages.push({ ok: r.status === 200 && !json.error_code, stage: 'register', status: r.status, body: r.body.slice(0, 500), error: json.error_code ? `error_code ${json.error_code}` : null });
  return { ...result, ok: r.status === 200 && !json.error_code, status: r.status, response: json };
}

module.exports = { register, mfc, integrity, arkose, newAccount, MFC, GQL, REGISTER };
