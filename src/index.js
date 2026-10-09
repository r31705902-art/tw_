'use strict';
// Entrypoint. Boots: config -> logger -> telegram -> proxy pool -> agent -> bot.
// Plus a tiny health server so Railway's healthcheck has something to hit.
const cfg = require('./config');
const log = require('./logger');
const notify = require('./notify');
const fs = require('fs');
const path = require('path');
const { ProxyPool } = require('./proxy');
const { Agent } = require('./agent');
const { TgBot } = require('./bot');
const state = require('./state');

start().catch(e => {
  log.critical('boot', `fatal: ${e.message}\n${e.stack || ''}`);
  notify.critical(`boot fatal: ${e.message}`);
  process.exit(1);
});

async function pickWorkingModel() {
  const llm = require('./llm');
  // Probe the CONFIGURED model first. Walking the whole catalogue burns quota
  // on providers that are already known dead and delays boot for no gain.
  const configured = state.load().model;
  const order = [configured];
  for (const m of ['nvidia:moonshotai/kimi-k3', 'openrouter:nvidia/nemotron-3-ultra-550b-a55b:free']) {
    if (!order.includes(m)) order.push(m);
  }

  for (const model of order) {
    if (!model) continue;
    try {
      const r = await llm.chat({
        model,
        messages: [{ role: 'user', content: 'reply with the single word: ready' }],
        maxTokens: 256,
      });
      if ((r.text || '').trim() || r.toolCalls.length) {
        log.info('boot', `model probe ok: ${model}`);
        return model;
      }
      log.debug('boot', `probe ${model}: empty reply`);
    } catch (e) {
      log.debug('boot', `probe ${model}: ${e.message.slice(0, 90)}`);
    }
  }
  return null;
}

async function start() {
  log.info('boot', `workspace=${cfg.workspaceDir} data=${cfg.dataDir}`);

  if (!notify.enabled) {
    log.warn('boot', 'TG_BOT_TOKEN/TG_CHAT_ID missing — running without telegram');
  }

  const pool = new ProxyPool(notify);
  const agent = new Agent(pool);
  const bot = new TgBot(agent, pool);
  agent.bot = bot;
  bot.start();

  // pick a model that actually answers: probe the free tier and the stealth
  // lane once, then fall back along the catalogue until one replies.
  const usable = await pickWorkingModel().catch(() => null);
  if (usable) state.patch({ model: usable });
  log.info('boot', `model -> ${state.load().model}`);

  agent.start();

  // seed the mission on a cold start so the box works unattended
  const s = state.load();
  if (!s.missionSeeded) {
    const mission = await fs.promises.readFile(path.join(cfg.root, 'TASK.md'), 'utf8').catch(() => '');
    agent.submit(
      'MISSION (http only, no browser). Read TASK.md. The registration pipeline must register a Twitch account over plain HTTP(S) — ' +
      'node-tls-client / node-fetch only. No chromium, no firefox, no camoufox, no puppeteer, no playwright anywhere in the final path; ' +
      'browser capture is a last resort the operator triggers by hand, never something you add to the pipeline. ' +
      'The task code in task/register/ is the proven Kasada chain; the only missing piece is the Arkose token that clears error_code 5021. ' +
      'Work in NOTES.md and iterate. Notify me on every real breakthrough and every hard failure.\n\n' + mission,
      'boot');
    state.patch({ missionSeeded: true, lastTask: 'mission' });
    log.info('boot', 'mission seeded');
  }

  // health + metrics endpoint
  const port = Number(process.env.PORT || 8080);
  const http = require('http');
  const server = http.createServer((req, res) => {
    const url = req.url || '/';
    if (url.startsWith('/health')) {
      res.writeHead(200, { 'content-type': 'application/json' });
      return res.end(JSON.stringify({ ok: true, uptime: process.uptime() }));
    }
    if (url.startsWith('/status')) {
      res.writeHead(200, { 'content-type': 'application/json' });
      return res.end(JSON.stringify({
        ...state.summary(),
        queue: agent.queue.length,
        rss: process.memoryUsage().rss,
        proxy: pool.status(),
      }, null, 2));
    }
    if (url.startsWith('/log')) {
      res.writeHead(200, { 'content-type': 'text/plain' });
      return res.end(log.tail(200));
    }
    res.writeHead(404); res.end('not found');
  });
  server.listen(port, () => log.info('boot', `health server on :${port}`));

  // keep the process honest
  const signals = ['SIGINT', 'SIGTERM'];
  for (const sig of signals) {
    process.on(sig, () => {
      log.warn('boot', `${sig} received, shutting down`);
      agent.stop();
      bot.stop();
      setTimeout(() => process.exit(0), 1500);
    });
  }

  // No boot ping: routine lifecycle must not reach the chat. Only genuine
  // failures below are pushed. The agent notifies on breakthroughs itself
  // through the notify tool.
  process.on('unhandledRejection', err => {
    log.error('boot', `unhandledRejection: ${err && err.message}`);
    notify.error(`unhandled rejection: ${err && err.message}`);
  });
  process.on('uncaughtException', err => {
    log.critical('boot', `uncaughtException: ${err && err.message}`);
    notify.critical(`uncaught exception: ${err && err.message}`);
  });
}
