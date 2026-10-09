'use strict';
const path = require('path');
const fs = require('fs');

// ---- env bootstrap --------------------------------------------------------
try {
  const dotenv = require('dotenv');
  const envFile = path.join(__dirname, '..', '.env');
  if (fs.existsSync(envFile)) dotenv.config({ path: envFile });
  else dotenv.config();
} catch (e) {
  console.warn('[config] dotenv unavailable, reading process.env only');
}

function csv(v) {
  return String(v || '').split(',').map(s => s.trim()).filter(Boolean);
}

const ROOT = path.join(__dirname, '..');
const DATA_DIR = path.resolve(process.env.DATA_DIR || path.join(ROOT, 'data'));
const WORKSPACE_DIR = path.resolve(process.env.WORKSPACE_DIR || ROOT);

for (const d of [DATA_DIR, path.join(DATA_DIR, 'logs'), WORKSPACE_DIR]) {
  try { fs.mkdirSync(d, { recursive: true }); } catch (e) { }
}

const config = {
  root: ROOT,
  dataDir: DATA_DIR,
  logDir: path.join(DATA_DIR, 'logs'),
  workspaceDir: WORKSPACE_DIR,
  stateFile: path.join(DATA_DIR, 'state.json'),

  telegram: {
    token: process.env.TG_BOT_TOKEN || '',
    chatId: process.env.TG_CHAT_ID || '',
    pollIntervalMs: Number(process.env.TG_POLL_MS || 2500),
    // telegram hard limit ~1 msg/s per chat; a little headroom
    minSendGapMs: 1100,
    maxQueue: 500,
  },

  notifyLevels: new Set(csv(process.env.NOTIFY_LEVELS || 'info,warn,error,critical')),

  llm: {
    openrouter: { keys: csv(process.env.OPENROUTER_KEYS), baseUrl: process.env.OPENROUTER_BASE_URL || 'https://openrouter.ai/api/v1' },
    nvidia: { keys: csv(process.env.NVIDIA_API_KEY), baseUrl: process.env.NVIDIA_BASE_URL || 'https://integrate.api.nvidia.com/v1' },
    tokenharbor: { keys: csv(process.env.TOKENHARBOR_API_KEY), baseUrl: process.env.TOKENHARBOR_BASE_URL || 'https://api.tokenharbor.ai/v1' },
    opencodezen: { keys: csv(process.env.OPENCODE_ZEN_API_KEY), baseUrl: process.env.OPENCODE_ZEN_BASE_URL || 'https://opencode.ai/zen/v1' },
    timeoutMs: Number(process.env.LLM_TIMEOUT_MS || 120000),
    retries: Number(process.env.LLM_RETRIES || 2),
  },

  agent: {
    model: process.env.AGENT_MODEL || 'openrouter:meta-llama/llama-3.3-70b-instruct',
    maxTurns: Number(process.env.AGENT_MAX_TURNS || 30),
    temperature: Number(process.env.AGENT_TEMPERATURE || 0.2),
  },

  shell: {
    timeoutMs: Number(process.env.SHELL_TIMEOUT_MS || 60000),
    maxTimeoutMs: Number(process.env.SHELL_MAX_TIMEOUT_MS || 600000),
    maxOutputBytes: Number(process.env.SHELL_MAX_OUTPUT || 60000),
  },

  proxy: {
    oxy: {
      username: process.env.OXY_USERNAME || '',
      password: process.env.OXY_PASSWORD || '',
      host: process.env.OXY_HOST || 'pr.oxylabs.io',
      port: Number(process.env.OXY_PORT || 7777),
      session: process.env.OXY_SESSION || String(Date.now()).slice(-10),
      sesstime: Number(process.env.OXY_SESSTIME || 10),
      country: (process.env.OXY_COUNTRY || '').toLowerCase(),
      city: (process.env.OXY_CITY || '').toLowerCase(),
      protocol: process.env.OXY_PROTOCOL || 'http',
    },
    dcFile: path.resolve(process.env.DC_PROXY_FILE || path.join(ROOT, 'proxies.txt')),
  },
};

module.exports = config;
