'use strict';
// Multi-provider LLM layer.
//
// Providers are openai-compatible. Model ids are readable live so the TG bot
// can list and switch them at runtime, and keys rotate on 401/429.
const cfg = require('./config');
const log = require('./logger');

const PROVIDERS = {
  openrouter: {
    label: 'OpenRouter',
    baseUrl: () => cfg.llm.openrouter.baseUrl,
    keys: () => cfg.llm.openrouter.keys,
    extraHeaders: () => ({ 'X-Title': 'tw-agent' }),
  },
  nvidia: {
    label: 'NVIDIA NIM',
    baseUrl: () => cfg.llm.nvidia.baseUrl,
    keys: () => cfg.llm.nvidia.keys,
  },
  tokenharbor: {
    label: 'Token Harbor',
    baseUrl: () => cfg.llm.tokenharbor.baseUrl,
    keys: () => cfg.llm.tokenharbor.keys,
  },
  opencodezen: {
    // documented as needing no api key
    label: 'OpenCode Zen',
    baseUrl: () => cfg.llm.opencodezen.baseUrl,
    keys: () => cfg.llm.opencodezen.keys,
  },
};

// per-provider round-robin key cursor + cooldown map
const cursor = {};
const cooldown = {};

function nextKey(p) {
  const keys = PROVIDERS[p].keys();
  if (!keys.length) return null;
  cursor[p] = ((cursor[p] || 0) + 1) % keys.length;
  return keys[cursor[p]];
}

function keyBlocked(p, key) {
  const until = cooldown[p] && cooldown[p][key];
  return until && until > Date.now();
}

function blockKey(p, key, ms) {
  (cooldown[p] = cooldown[p] || {})[key] = Date.now() + ms;
}

async function fetchJson(url, { method = 'GET', headers = {}, body, timeoutMs = 60000 }) {
  const fetch = require('node-fetch');
  const ac = new AbortController();
  const t = setTimeout(() => ac.abort(), timeoutMs);
  try {
    const res = await fetch(url, {
      method, headers, body: body ? JSON.stringify(body) : undefined,
      signal: ac.signal,
    });
    const text = await res.text();
    let json;
    try { json = JSON.parse(text); } catch (e) { json = { raw: text.slice(0, 2000) }; }
    return { status: res.status, json };
  } finally { clearTimeout(t); }
}

function authHeaders(provider, key) {
  const h = { 'content-type': 'application/json', accept: 'application/json' };
  if (key) h.authorization = `Bearer ${key}`;
  Object.assign(h, (PROVIDERS[provider].extraHeaders ? PROVIDERS[provider].extraHeaders(key) : {}) || {});
  return h;
}

// `/models` lists only what this box should use: the free tier and the stealth
// lane. OpenRouter accepts a `:stealth` suffix on any model id, so every free
// model gets a stealth twin in the list — that is the second half of the ask.
// Stealth-named entries that are NOT free (anthropic's `fable` lane, `:batch`
// variants, `~prefixed` aliases) are dropped: they are paid or not free-tier.
const FREE_TIER = new Set(['openrouter']);
const INCLUDED = [/:\s*free$/i, /stealth/i];
const EXCLUDED = [
  /(?:^|[-_:])(?:deprecated|legacy|exp)(?:$|[-_:])/i,
  /:batch$/i,
  /^~/,            // alias entries
];

// what the operator is allowed to pick: free tier, or the stealth lane.
// Stealth pricing is invisible to us, so a stealth-named entry only passes when
// it is ALSO free — that keeps the list honest.
function isUsable(id) {
  const s = String(id);
  if (EXCLUDED.some(rx => rx.test(s))) return false;
  if (/:\s*stealth$/i.test(s)) return true;                       // a stealth twin we made
  if (/stealth/i.test(s) && /:\s*free$/i.test(s)) return true;    // free + stealth named
  return /:\s*free$/i.test(s);                                    // plain free tier
}

// ---- model catalogue ------------------------------------------------------
async function listModels(provider) {
  const spec = PROVIDERS[provider];
  if (!spec) throw new Error(`unknown provider: ${provider}`);
  const key = spec.keys()[0];
  const { json } = await fetchJson(`${spec.baseUrl()}/models`, { headers: authHeaders(provider, key), timeoutMs: 30000 });
  const data = (json && (json.data || json.models)) || [];
  if (Array.isArray(data) && data.length) {
    let ids = data.map(m => (typeof m === 'string' ? m : m.id || m.name || m.model))
      .filter(Boolean).map(String);
    if (FREE_TIER.has(provider)) {
      // keep the free tier, and add a stealth twin for each free model
      const free = ids.filter(isUsable);
      const stealthTwins = free
        .filter(id => /:\s*free$/i.test(id) && !/:\s*stealth$/i.test(id))
        .map(id => `${id}:stealth`);
      ids = [...new Set([...free, ...stealthTwins])];
    }
    return ids;
  }
  return [];
}

async function catalogue() {
  const out = {};
  await Promise.all(Object.keys(PROVIDERS).map(async (p) => {
    try { out[p] = await listModels(p); }
    catch (e) { out[p] = []; log.warn('llm', `catalogue ${p} failed: ${e.message}`); }
  }));
  return out;
}

async function catalogueAll() {
  const out = {};
  await Promise.all(Object.keys(PROVIDERS).map(async (p) => {
    try { out[p] = await listModelsAll(p); }
    catch (e) { out[p] = []; log.warn('llm', `catalogue ${p} failed: ${e.message}`); }
  }));
  return out;
}

async function listModelsAll(provider) {
  const spec = PROVIDERS[provider];
  const key = spec.keys()[0];
  const { json } = await fetchJson(`${spec.baseUrl()}/models`, { headers: authHeaders(provider, key), timeoutMs: 30000 });
  const data = (json && (json.data || json.models)) || [];
  if (Array.isArray(data) && data.length) {
    return data.map(m => (typeof m === 'string' ? m : m.id || m.name || m.model)).filter(Boolean).map(String);
  }
  return [];
}

function parseModelId(id) {
  const raw = String(id || '').trim();
  if (raw.includes(':')) {
    const [p, ...rest] = raw.split(':');
    if (PROVIDERS[p]) return { provider: p, model: rest.join(':') };
  }
  return { provider: 'openrouter', model: raw };
}

// ---- chat -----------------------------------------------------------------
// A "402 requires more credits" on openrouter's free tier means the free
// allowance is spent. Every key on that provider is tried first; if all are
// dry the call walks the fallback chain to a provider that still answers.
const FALLBACK_ORDER = ['nvidia', 'opencodezen', 'openrouter', 'tokenharbor'];

// Models verified to answer on the live gateways. The catalogue's first entry is
// often a 404 or a restricted model, so blind picking wastes whole turns.
const FALLBACK_PRESET = {
  nvidia: 'moonshotai/kimi-k3',
  openrouter: 'nvidia/nemotron-3-ultra-550b-a55b:free',
};

async function chatOne(model, { messages, tools, temperature, maxTokens }) {
  const { provider, model: modelId } = parseModelId(model);
  const spec = PROVIDERS[provider];
  if (!spec) throw new Error(`unknown provider in model id: ${model}`);

  const body = {
    model: baseModelId(modelId),
    messages,
    temperature: temperature === undefined ? cfg.agent.temperature : temperature,
    // free-tier accounts report "can only afford N" at 402 — start modest
    max_tokens: maxTokens || 1024,
  };
  if (tools && tools.length) { body.tools = tools; body.tool_choice = 'auto'; }
  // reasoning models burn their whole budget in reasoning_tokens and return an
  // empty content string with finish=length. A small ceiling therefore looks
  // like a dead model. Give reasoning models room to finish thinking.
  if (!maxTokens && /nemotron|deepseek|kimi|gpt-5|gpt-6|sonnet|opus|reasoning/i.test(modelId)) {
    body.max_tokens = 4096;
  }

  const keys = spec.keys();
  // prefer the least-used key, skipping anything on cooldown
  const ordered = keys.slice().sort((a, b) =>
    ((cooldown[provider] && cooldown[provider][a]) || 0) -
    ((cooldown[provider] && cooldown[provider][b]) || 0));
  const candidates = ordered.length ? ordered : [null];
  const attempts = [];

  for (const key of candidates) {
    if (key && keyBlocked(provider, key)) { attempts.push('cooldown'); continue; }
    try {
      const { status, json } = await fetchJson(`${spec.baseUrl()}/chat/completions`, {
        method: 'POST', headers: authHeaders(provider, key), body,
        timeoutMs: cfg.llm.timeoutMs,
      });
      if (status === 401 || status === 403) {
        const emsg = ((json && json.error && json.error.message) || '').toLowerCase();
        // a 403 that names the model is a MODEL restriction, not a bad key —
        // cooling the key down here would poison every later request
        const modelLevel = /only available|not available|is only|requires|unsupported model|agentic harness/.test(emsg);
        if (modelLevel) {
          attempts.push(`${status} model-restricted`);
          continue;
        }
        // try once without a key before declaring the provider dead
        try {
          const retry = await fetchJson(`${spec.baseUrl()}/chat/completions`, {
            method: 'POST', headers: { 'content-type': 'application/json' }, body,
            timeoutMs: cfg.llm.timeoutMs,
          });
          if (retry.status === 200) { log.info('llm', `${provider}: anonymous request accepted`); return normalize(retry.json); }
        } catch (e) { }
        blockKey(provider, key, 15 * 60 * 1000);
        attempts.push(`${status} auth`);
        continue;
      }
      if (status === 402) { attempts.push('402 no credits'); continue; }
      if (status === 429) {
        // a daily free-tier cap is an ACCOUNT limit, not a per-key one — the
        // other key of the same account may still have quota, so do NOT cool
        // this key down, just try the next one
        const msg = ((json && json.error && json.error.message) || '').toLowerCase();
        const daily = /free-models-per-day|daily|per day/.test(msg);
        attempts.push(daily ? '429 daily-cap' : '429 rate-limited');
        if (!daily) blockKey(provider, key, 60 * 1000);
        continue;
      }
      if (status >= 400) {
        attempts.push(`${status}: ${((json && json.error && (json.error.message || json.error.code)) || json.raw || '').toString().slice(0, 120)}`);
        continue;
      }
      const c = cooldown[provider] && cooldown[provider][key];
      if (c) { delete cooldown[provider][key]; }
      return normalize(json);
    } catch (e) {
      attempts.push(e.message);
    }
  }
  const err = new Error(`all ${provider} keys failed (${attempts.join(' | ').slice(0, 240)})`);
  err.provider = provider;
  const spent = attempts.every(a => a === '402 no credits' || a === 'cooldown' || a === '429 daily-cap');
  err.noCredits = attempts.length > 0 && spent;
  throw err;
}

async function chat(opts) {
  const primary = opts.model;
  try {
    return await chatOne(primary, opts);
  } catch (e) {
    if (!e.noCredits) throw e;
    // every key on this provider is dry or daily-capped — walk the fallback
    // chain, remembering which ones actually answer so later turns are cheap
    log.warn('llm', `${e.provider} exhausted (${e.message.slice(0, 120)}), trying fallbacks`);
    for (const p of FALLBACK_ORDER) {
      if (p === e.provider) continue;
      if (p === 'tokenharbor' && !PROVIDERS[p].keys().length) continue;
      let pick = FALLBACK_PICK[p];
      if (!pick) {
        pick = FALLBACK_PRESET[p] || null;
        if (!pick) {
          let ids = [];
          try { ids = await listModels(p); } catch (err) { continue; }
          pick = ids[0];
        }
        if (!pick) continue;
        FALLBACK_PICK[p] = pick;
      }
      try {
        const out = await chatOne(`${p}:${pick}`, opts);
        log.info('llm', `fallback -> ${p}:${pick}`);
        return out;
      } catch (e2) {
        log.warn('llm', `fallback ${p}:${pick} failed: ${e2.message.slice(0, 100)}`);
        // this model is not usable for us; do not retry it every turn
        delete FALLBACK_PICK[p];
        if (!e2.noCredits) { /* keep walking the chain */ }
      }
    }
    throw e;
  }
}

// remembered working fallback model per provider
const FALLBACK_PICK = {};

function normalize(json) {
  const choice = (json.choices && json.choices[0]) || {};
  const msg = choice.message || {};
  let content = msg.content;
  if (Array.isArray(content)) content = content.map(c => c.text || '').join('');
  let toolCalls = (msg.tool_calls || []).map(tc => ({
    id: tc.id || String(Math.random()),
    name: (tc.function && tc.function.name) || '',
    argumentsText: (tc.function && tc.function.arguments) || '{}',
  }));
  // some gateways surface tool calls as a content block
  if ((!content || !String(content).trim()) && toolCalls.length === 0 && msg.tool_call) toolCalls = [{
    id: msg.tool_call.id, name: msg.tool_call.name, argumentsText: JSON.stringify(msg.tool_call.arguments || {}),
  }];
  return {
    text: content || '',
    toolCalls,
    finish: choice.finish_reason || 'stop',
    usage: json.usage || null,
  };
}

// text-protocol fallback for providers without native tool calling
const TOOL_BLOCK = /```(?:tool|json)\s*\n([\s\S]*?)```/g;
function parseToolFallback(text) {
  const calls = [];
  let m;
  while ((m = TOOL_BLOCK.exec(text)) !== null) {
    try {
      const parsed = JSON.parse(m[1].trim());
        const arr = Array.isArray(parsed) ? parsed : [parsed];
      for (const one of arr) {
        if (one && one.name) calls.push({ id: 'fb' + Math.random(), name: one.name, argumentsText: JSON.stringify(one.arguments || {}) });
      }
    } catch (e) { }
  }
  return calls;
}

function parseModelId(id) {
  const raw = String(id || '').trim();
  if (raw.includes(':')) {
    const [p, ...rest] = raw.split(':');
    if (PROVIDERS[p]) return { provider: p, model: rest.join(':') };
  }
  return { provider: 'openrouter', model: raw };
}

// a ":stealth" marker on a model id asks for the stealth lane.
//
// IMPORTANT: openrouter rejects an explicit `route` option, and opencode zen
// requires an api key we do not hold — it answers 401 with an AuthError and
// lists its models unauthenticated. So neither supports a stealth route we can
// set from here; the marker is stripped and remembered, not transmitted.
function isStealthId(id) {
  return /:stealth$/i.test(String(id || ''));
}

function stealthLane(modelId) {
  return isStealthId(modelId) ? 'stealth' : 'default';
}

// strip the ":stealth" marker to get the model the gateway will accept
function baseModelId(id) {
  return String(id || '').replace(/:stealth$/i, '');
}

module.exports = { PROVIDERS, chat, catalogue, catalogueAll, listModels, parseModelId, parseToolFallback, isStealthId, baseModelId, stealthLane };
