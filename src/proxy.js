'use strict';
// Proxy pool: residential (oxylabs) -> datacenter (proxies.txt) -> direct.
// Rotates on failure, circuit-breaks per tier, and survives balance exhaustion.
const fs = require('fs');
const cfg = require('./config');
const log = require('./logger');

const TIERS = ['residential', 'datacenter', 'direct'];

function oxyUrl({ session, sesstime, country, city, protocol }) {
  const o = cfg.proxy.oxy;
  const parts = ['customer', o.username];
  if (session) parts.push(`sessid-${session}`);
  if (sesstime) parts.push(`sesstime-${sesstime}`);
  if (country) parts.push(`cc-${country}`);
  if (city) parts.push(`city-${city}`);
  const auth = `${parts.join('-')}:${encodeURIComponent(o.password)}`;
  return `${protocol || o.protocol}://${auth}@${o.host}:${o.port}`;
}

class ProxyPool {
  constructor(notify) {
    this.notify = notify;
    this.mode = 'residential';
    this.session = cfg.proxy.oxy.session;
    this.sesstime = cfg.proxy.oxy.sesstime;
    this.country = cfg.proxy.oxy.country;
    this.city = cfg.proxy.oxy.city;
    this.protocol = cfg.proxy.oxy.protocol;
    this.dc = this.loadDc();
    this.dcIndex = 0;
    this.failures = { residential: 0, datacenter: 0, direct: 0 };
    this.cooldownUntil = { residential: 0, datacenter: 0, direct: 0 };
    this.balanceExhausted = false;
  }

  loadDc() {
    try {
      const txt = fs.readFileSync(cfg.proxy.dcFile, 'utf8');
      // ignore comments (# or //) and blank lines
      return txt.split(/\r?\n/)
        .map(l => l.trim())
        .filter(l => l && !l.startsWith('#') && !l.startsWith('//'))
        .map(line => {
          const [host, port, user, pass] = line.split(':');
          if (!host || !port) return null;
          return { url: `http://${user}:${encodeURIComponent(pass || '')}@${host}:${port}`, host };
        })
        .filter(Boolean);
    } catch (e) {
      log.warn('proxy', `dc list unavailable: ${e.message}`);
      return [];
    }
  }

  setMode(mode) {
    if (!TIERS.includes(mode)) throw new Error(`mode must be one of ${TIERS.join('|')}`);
    this.mode = mode;
    this.failures[mode] = 0;
    this.cooldownUntil[mode] = 0;
    log.info('proxy', `mode -> ${mode}`);
    if (this.notify) this.notify.info(`proxy mode → *${mode}*`);
  }

  newSession() {
    this.session = String(Math.floor(Math.random() * 9000000000) + 1000000000);
    this.cooldownUntil.residential = 0;
    this.failures.residential = 0;
    log.info('proxy', `new residential session ${this.session}`);
  }

  setGeo({ country, city }) {
    this.country = String(country || '').toLowerCase();
    this.city = String(city || '').toLowerCase();
    this.newSession();
  }

  setSesstime(min) { this.sesstime = Number(min) || 10; this.newSession(); }
  setProtocol(p) {
    if (!/^(http|https|socks5|socks5h)$/i.test(p)) throw new Error('protocol must be http|https|socks5|socks5h');
    this.protocol = p.toLowerCase();
  }

  current() {
    if (this.balanceExhausted) return { kind: 'direct', url: null, note: 'balance exhausted' };
    if (Date.now() < this.cooldownUntil[this.mode]) return this.next();
    return this.pick(this.mode);
  }

  pick(mode) {
    if (mode === 'direct') return { kind: 'direct', url: null };
    if (mode === 'residential') {
      if (!cfg.proxy.oxy.username || !cfg.proxy.oxy.password) return { kind: 'direct', url: null, note: 'no residential credentials' };
      return { kind: 'residential', url: oxyUrl(this), session: this.session };
    }
    if (!this.dc.length) return { kind: 'direct', url: null, note: 'no datacenter list' };
    this.dcIndex = (this.dcIndex + 1) % this.dc.length;
    return { kind: 'datacenter', url: this.dc[this.dcIndex].url, host: this.dc[this.dcIndex].host };
  }

  next() {
    const i = TIERS.indexOf(this.mode);
    this.mode = TIERS[Math.min(TIERS.length - 1, i + 1)];
    this.failures[this.mode] = 0;
    log.warn('proxy', `degrading to ${this.mode}`);
    if (this.notify) this.notify.warn(`proxy failed, degrading → *${this.mode}*`);
    return this.pick(this.mode);
  }

  report(kind, ok, detail) {
    this.failures[kind] = ok ? 0 : this.failures[kind] + 1;
    if (ok) return;
    if (this.failures[kind] >= 3) {
      this.cooldownUntil[kind] = Date.now() + 60000;
      log.warn('proxy', `${kind} circuit open 60s (${detail || ''})`);
      if (kind === 'residential' && /balance|402|Unauthorized|auth/i.test(detail || '')) {
        this.balanceExhausted = true;
        log.critical('proxy', 'residential balance exhausted -> direct mode');
        if (this.notify) this.notify.critical('proxy balance exhausted → falling back to own IP');
      }
    }
  }

  status() {
    return {
      mode: this.mode,
      session: this.session,
      sesstime: this.sesstime,
      geo: { country: this.country || null, city: this.city || null },
      protocol: this.protocol,
      dcList: this.dc.length,
      failures: this.failures,
      balanceExhausted: this.balanceExhausted,
    };
  }
}

module.exports = { ProxyPool, oxyUrl, TIERS };
