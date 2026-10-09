'use strict';
// Telegram control surface.
//
//   /start /stop /status /models /model <provider:model> /msg <task>
//   /log [n] /errors /proxy <mode> /proxygeo <cc> <city> /proxynew
//   /sesstime <min> /protocol <http|https|socks5> /balance /shell <cmd>
//   /help
//
// Any non-command text is handed to the agent as a task.
const cfg = require('./config');
const log = require('./logger');
const notify = require('./notify');
const state = require('./state');
const llm = require('./llm');
const { runTool } = require('./tools');

const started = { at: null };

class TgBot {
  constructor(agent, pool) {
    this.agent = agent;
    this.pool = pool;
    this.offset = 0;
    this.running = false;
    this.userIds = new Set(String(cfg.telegram.chatId).split(',').map(s => s.trim()).filter(Boolean));
  }

  allowed(msg) {
    const id = String(msg.chat && msg.chat.id);
    if (!this.userIds.size) return true;             // unset: accept all
    if (this.userIds.has(id)) return true;
    notify.warn(`ignored message from unknown chat ${id}`);
    return false;
  }

  // node-fetch puts the full request URL in its error messages, and that URL
  // contains the bot token. Mask it before anything reaches a log file.
  mask(msg) {
    return String(msg || '').split(cfg.telegram.token).join('<BOT_TOKEN>');
  }

  async api(method, body) {
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

  start() {
    if (!notify.enabled) { log.warn('bot', 'telegram not configured; bot disabled'); return; }
    this.running = true;
    started.at = Date.now();
    log.info('bot', 'telegram bot polling');
    this.poll().catch(e => { log.error('bot', `poll died: ${this.mask(e.message)}`); this.running = false; });
  }

  stop() {
    this.running = false;
    log.info('bot', 'bot stopped');
  }

  async poll() {
    while (this.running) {
      try {
        const updates = await this.api('getUpdates', {
          offset: this.offset, timeout: 25, allowed_updates: ['message'],
        });
        for (const u of updates) {
          this.offset = u.update_id + 1;
          if (u.message) this.handle(u.message).catch(e => log.warn('bot', `handle: ${this.mask(e.message)}`));
        }
      } catch (e) {
        log.warn('bot', `poll error: ${this.mask(e.message)}`);
        await sleep(Math.max(2000, cfg.telegram.pollIntervalMs));
      }
      await sleep(cfg.telegram.pollIntervalMs);
    }
  }

  async handle(msg) {
    if (!this.allowed(msg)) return;
    const text = (msg.text || '').trim();
    if (!text) return;
    log.info('bot', `<- ${text.slice(0, 200)}`);
    const [cmd, ...rest] = text.split(/\s+/);
    const arg = rest.join(' ');
    const low = cmd.toLowerCase();

    try {
      if (low === '/start') return this.cmdStart();
      if (low === '/stop') return this.agent.stop();
      if (low === '/status') return this.cmdStatus();
      if (low === '/models') return this.cmdModels();
      if (low === '/model') return this.cmdModel(arg);
      if (low === '/msg' || low === '/task') return this.agent.submit(arg, 'telegram');
      if (low === '/log') return this.cmdLog(Number(rest[0]) || 40);
      if (low === '/errors') return this.cmdErrors();
      if (low === '/proxy') return this.cmdProxy(arg);
      if (low === '/proxygeo') return this.cmdProxyGeo(rest);
      if (low === '/proxynew') { this.pool.newSession(); return notify.say('new residential session'); }
      if (low === '/sesstime') { this.pool.setSesstime(arg); return notify.say(`sesstime → ${this.pool.sesstime}m`); }
      if (low === '/protocol') { this.pool.setProtocol(arg); return notify.say(`protocol → ${this.pool.protocol}`); }
      if (low === '/balance') return this.cmdBalance();
      if (low === '/shell') return this.cmdShell(arg);
      if (low === '/help' || low === '/menu') return this.cmdHelp();
      if (text.startsWith('/')) return notify.say(`unknown command: ${cmd} — /help`);
      // plain text is a task for the agent
      return this.agent.submit(text, 'telegram');
    } catch (e) {
      log.error('bot', `command ${cmd} failed: ${this.mask(e.message)}`);
      notify.error(`command failed: ${this.mask(e.message)}`);
    }
  }

  cmdStart() {
    if (this.agent.running) return notify.say('agent already running');
    return this.agent.start().then(ok => { if (!ok) notify.say('could not start'); });
  }

  cmdStatus() {
    const s = state.summary();
    const mem = process.memoryUsage();
    notify.say([
      `*status*`,
      `running: ${s.running ? 'yes' : 'no'}`,
      `model: \`${s.model}\``,
      `proxy: ${this.pool.status().mode} (balance exhausted: ${this.pool.status().balanceExhausted})`,
      `turns used: ${s.turnsUsed}`,
      `queue: ${this.agent.queue.length}`,
      `rss: ${(mem.rss / 1048576).toFixed(0)} MB, heap ${(mem.heapUsed / 1048576).toFixed(0)} MB`,
      `uptime: ${Math.floor(process.uptime())}s`,
      `last task: ${(s.lastTask || '-').slice(0, 200)}`,
      `last error: ${(s.lastError || '-').slice(0, 200)}`,
    ].join('\n'));
  }

  async cmdModels() {
    const all = process.argv && process.argv.includes('--all');
    const savedTier = all ? null : true;
    const cat = all ? await llm.catalogueAll() : await llm.catalogue();
    const lines = ['*catalogue*'];
    let total = 0;
    for (const p of Object.keys(cat)) {
      const models = cat[p];
      total += models.length;
      lines.push(`\n*${p}* (${models.length})`);
      models.slice(0, 40).forEach(m => lines.push(`  \`${m}\``));
      if (models.length > 40) lines.push(`  … +${models.length - 40} more`);
    }
    if (!total) lines.push('\n(no preferred models found — is any key alive?)');
    notify.say(lines.join('\n').slice(0, 3900));
  }

  async cmdModel(arg) {
    if (!arg) return notify.say(`usage: /model <provider:model> — current \`${state.load().model}\``);
    const { provider, model } = llm.parseModelId(arg);
    if (!llm.PROVIDERS[provider]) return notify.say(`unknown provider: ${provider}. try: ${Object.keys(llm.PROVIDERS).join(', ')}`);
    const full = `${provider}:${model}`;

    // catalogue check first — cheap, catches typos
    try {
      const ids = await llm.listModels(provider);
      if (ids.length && !ids.includes(model) && !ids.includes(llm.baseModelId(model))) {
        return notify.say(`\`${model}\` is not in ${provider}'s catalogue.\nsample: ${ids.slice(0, 8).join(', ')}`);
      }
    } catch (e) { /* catalogue unreachable: fall through to the live probe */ }

    // then a real request. The catalogue lists globally-available models, not
    // the ones deployed for this account — only a live call settles it.
    try {
      const r = await llm.chat({
        model: full,
        messages: [{ role: 'user', content: 'Reply with exactly: ready' }],
        maxTokens: 256,
      });
      const got = (r.text || '').trim().slice(0, 40);
      state.patch({ model: full });
      notify.say(`model → \`${full}\`\nprobe ok${got ? `: ${got}` : ''}`);
    } catch (e) {
      notify.say([
        `\`${full}\` did NOT answer.`,
        ``,
        `\`${this.mask(String(e.message).slice(0, 300))}\``,
        ``,
        `model unchanged: \`${state.load().model}\``,
      ].join('\n'));
    }
  }

  cmdLog(n) { notify.say('```\n' + log.tail(n).slice(0, 3800) + '\n```'); }

  cmdErrors() {
    const errs = log.all().filter(l => /WARN|ERROR|CRITICAL/.test(l)).slice(-40);
    notify.say('```\n' + (errs.join('\n') || 'no recent warnings/errors').slice(0, 3800) + '\n```');
  }

  cmdProxy(mode) {
    this.pool.setMode(mode);
    const s = this.pool.status();
    state.patch({ proxyMode: mode });
    notify.say(`proxy → *${s.mode}*\nsession \`${s.session}\` sesstime ${s.sesstime}m geo ${s.geo.country || 'any'}/${s.geo.city || 'any'} ${s.protocol}`);
  }

  cmdProxyGeo(rest) {
    const [cc, city = ''] = rest;
    if (!cc) return notify.say('usage: /proxygeo <country> [city]');
    this.pool.setGeo({ country: cc, city });
    notify.say(`geo → ${cc}${city ? '/' + city : ''} (new session)`);
  }

  async cmdBalance() {
    // oxylabs exposes no balance endpoint on the proxy port; we can only report
    // what we have observed. The pool flags exhaustion from 402/auth responses.
    const s = this.pool.status();
    notify.say([
      `residential balance: ${s.balanceExhausted ? '*exhausted (direct mode)*' : 'assumed active (unverifiable from proxy port)'}`,
      `failures: ${JSON.stringify(s.failures)}`,
      `mode: ${s.mode}`,
    ].join('\n'));
  }

  async cmdShell(cmd) {
    if (!cmd) return notify.say('usage: /shell <allowlisted command>');
    const out = await runTool('run_script', { cmd, timeoutMs: 60000 });
    notify.say('```\n' + out.slice(0, 3800) + '\n```');
  }

  cmdHelp() {
    notify.say([
      '*tw-agent commands*',
      '/start — start the agent',
      '/stop — stop mid-task',
      '/status — running state, model, proxy, memory',
      '/models — live catalogue from every provider',
      '/model provider:model — switch model',
      '/msg <text> — send a task to the agent',
      '/log [n] — last log lines',
      '/errors — warnings and errors only',
      '/proxy residential|datacenter|direct — switch tier',
      '/proxygeo <cc> [city] — repin residential exit',
      '/proxynew — new residential session id',
      '/sesstime <min> — sticky session lifetime',
      '/protocol http|https|socks5',
      '/balance — residential balance state',
      '/shell <cmd> — run an allowlisted command',
      '/help — this text',
    ].join('\n'));
  }
}

const sleep = (ms) => new Promise(r => setTimeout(r, ms));
module.exports = { TgBot };
