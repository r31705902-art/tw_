'use strict';
// Agent state, persisted to data/state.json with atomic writes.
const fs = require('fs');
const path = require('path');
const cfg = require('./config');

const DEFAULTS = {
  running: false,
  model: cfg.agent.model,
  temperature: cfg.agent.temperature,
  maxTurns: cfg.agent.maxTurns,
  startedAt: null,
  turnsUsed: 0,
  lastTask: null,
  lastResult: null,
  lastError: null,
  proxyMode: 'residential',   // residential | datacenter | direct
  history: [],                // last N messages, capped
};

let cache = null;

function load() {
  if (cache) return cache;
  try {
    if (fs.existsSync(cfg.stateFile)) {
      cache = Object.assign({}, DEFAULTS, JSON.parse(fs.readFileSync(cfg.stateFile, 'utf8')));
    } else {
      cache = { ...DEFAULTS };
    }
  } catch (e) {
    cache = { ...DEFAULTS };
  }
  return cache;
}

function save() {
  const tmp = cfg.stateFile + '.tmp';
  fs.mkdirSync(path.dirname(cfg.stateFile), { recursive: true });
  fs.writeFileSync(tmp, JSON.stringify(load(), null, 2));
  fs.renameSync(tmp, cfg.stateFile);
}

function patch(obj) {
  Object.assign(load(), obj);
  if (Array.isArray(cache.history) && cache.history.length > 60) {
    cache.history = cache.history.slice(-60);
  }
  save();
}

module.exports = {
  load, save, patch,
  reset() { cache = { ...DEFAULTS }; save(); },
  summary() {
    const s = load();
    return {
      running: s.running, model: s.model, proxyMode: s.proxyMode,
      turnsUsed: s.turnsUsed, lastTask: s.lastTask, lastError: s.lastError,
      startedAt: s.startedAt,
    };
  },
};
