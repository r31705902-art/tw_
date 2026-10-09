'use strict';
// Telegram transport: a rate-limited, bounded queue so the agent can spam logs
// without ever tripping Telegram's per-chat limits. Falls back to the log file
// when telegram is not configured.
const cfg = require('./config');
const log = require('./logger');

const enabled = Boolean(cfg.telegram.token && cfg.telegram.chatId);

const queue = [];
let sending = false;
let lastSentAt = 0;
const stats = { sent: 0, failed: 0, dropped: 0 };

function push(text) {
  if (!enabled) return false;
  if (queue.length >= cfg.telegram.maxQueue) { stats.dropped++; return false; }
  queue.push(String(text).slice(0, 3900));
  if (queue.length <= cfg.telegram.maxQueue) void 0;
  void pump();
  return true;
}

async function pump() {
  if (sending) return;
  sending = true;
  try {
    while (queue.length) {
      const gap = Date.now() - lastSentAt;
      if (gap < cfg.telegram.minSendGapMs) await sleep(cfg.telegram.minSendGapMs - gap);
      const text = queue.shift();
      try {
        await api('sendMessage', {
          chat_id: cfg.telegram.chatId,
          text: text.slice(0, 3900),
          disable_web_page_preview: true,
        });
        stats.sent++;
        lastSentAt = Date.now();
      } catch (e) {
        stats.failed++;
        // retry once after a pause; never lose the message silently
        await sleep(2000);
        try {
          await api('sendMessage', { chat_id: cfg.telegram.chatId, text: text.slice(0, 3900), disable_web_page_preview: true });
          stats.sent++;
          lastSentAt = Date.now();
        } catch (e2) {
          stats.failed++;
          log.warn('telegram', `send failed twice: ${e2.message}`);
        }
      }
    }
  } finally {
    sending = false;
  }
}

const sleep = (ms) => new Promise(r => setTimeout(r, ms));

async function api(method, body) {
  const fetch = require('node-fetch');
  const res = await fetch(`https://api.telegram.org/bot${cfg.telegram.token}/${method}`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  });
  const json = await res.json().catch(() => ({}));
  if (!json.ok) throw new Error(`telegram ${method}: ${json.description || res.status}`);
  return json.result;
}

// ---- notify API -----------------------------------------------------------
const notify = {
  enabled,
  push,
  stats: () => ({ ...stats, queue: queue.length }),
  level(level, message) {
    if (!cfg.notifyLevels.has(level)) return false;
    const icon = { info: 'ℹ️', warn: '⚠️', error: '❌', critical: '🚨' }[level] || '•';
    return push(`${icon} *${level.toUpperCase()}* — ${String(message).slice(0, 1200)}`);
  },
  info: (m) => notify.level('info', m),
  warn: (m) => notify.level('warn', m),
  error: (m) => notify.level('error', m),
  critical: (m) => notify.level('critical', m),
  // plain message, always delivered regardless of level filter
  say: (m) => push(String(m)),
};

module.exports = notify;
