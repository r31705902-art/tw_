'use strict';
const fs = require('fs');
const path = require('path');
const { EventEmitter } = require('events');
const cfg = require('./config');

// ---- tiny logger ----------------------------------------------------------
// levels: debug < info < warn < error < critical
const ORDER = { debug: 10, info: 20, warn: 30, error: 40, critical: 50 };
const state = { level: process.env.LOG_LEVEL || 'debug', lines: [] };
const MAX_RING = Number(process.env.LOG_RING || 300);

const bus = new EventEmitter();
bus.setMaxListeners(50);

function stamp() {
  return new Date().toISOString().replace('T', ' ').slice(0, 19);
}

function write(level, scope, msg, meta) {
  const line = `[${stamp()}] [${level.toUpperCase().padEnd(8)}] [${scope}] ${msg}`;
  state.lines.push(line);
  if (state.lines.length > MAX_RING) state.lines.splice(0, state.lines.length - MAX_RING);
  const consoleFn = level === 'debug' ? console.debug : (console[level] || console.log);
  consoleFn(line, meta === undefined ? '' : meta);
  bus.emit('line', { level, scope, msg, line });
  return line;
}

const logger = {
  onLine(fn) { bus.on('line', fn); return () => bus.off('line', fn); },
  tail(n = 40) { return state.lines.slice(-n).join('\n'); },
  all() { return state.lines.slice(); },
  setLevel(l) { state.level = l; },
  debug: (s, m, meta) => write('debug', s, m, meta),
  info: (s, m, meta) => write('info', s, m, meta),
  warn: (s, m, meta) => write('warn', s, m, meta),
  error: (s, m, meta) => write('error', s, m, meta),
  critical: (s, m, meta) => write('critical', s, m, meta),
};

// note: write() above is used before definition for clarity; reassign
for (const lvl of Object.keys(ORDER)) {
  logger[lvl] = (s, m, meta) => write(lvl, s, m, meta);
}

// ---- file sink ------------------------------------------------------------
let fileStream = null;
try {
  fs.mkdirSync(cfg.logDir, { recursive: true });
  const name = `agent-${new Date().toISOString().slice(0, 10)}.log`;
  const p = path.join(cfg.logDir, name);
  fileStream = fs.createWriteStream(p, { flags: 'a' });
  logger.onLine(({ line }) => {
    if (fileStream) fileStream.write(line + '\n', () => { });
  });
  logger.info('logger', `file sink -> ${p}`);
} catch (e) {
  logger.warn('logger', `file sink unavailable: ${e.message}`);
}

module.exports = logger;
