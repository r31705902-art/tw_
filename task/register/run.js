'use strict';
// CLI for one registration attempt.
//   node task/register/run.js                 # live, residential proxy
//   node task/register/run.js --direct        # no proxy
//   node task/register/run.js --browser camoufox
//   node task/register/run.js --dry           # stop after arkose stage
const cfg = require('../../src/config');
const log = require('../../src/logger');
const notify = require('../../src/notify');
const { ProxyPool } = require('../../src/proxy');
const reg = require('./register');

const args = process.argv.slice(2);
const has = (f) => args.includes(f);
const val = (f, d) => {
  const i = args.indexOf(f);
  return i >= 0 && args[i + 1] ? args[i + 1] : d;
};

(async () => {
  log.info('run', 'registration attempt starting');
  const pool = new ProxyPool(notify);
  if (has('--direct')) pool.setMode('direct');
  if (has('--datacenter')) pool.setMode('datacenter');
  const cc = val('--cc', '');
  const city = val('--city', '');
  if (cc) pool.setGeo({ country: cc, city });
  if (has('--new')) pool.newSession();

  const proxy = pool.current();
  log.info('run', `proxy -> ${proxy.kind} ${proxy.url ? proxy.url.replace(/:[^:@/]+@/, ':***@') : '(direct)'}`);

  try {
    const res = await reg.register(pool, { browser: has('--browser') ? (val('--browser', 'camoufox')) : null });

    log.info('run', 'stage report:');
    for (const s of res.stages) {
      log.info('run', `  ${s.ok ? 'OK  ' : 'FAIL'} ${s.stage}${s.error ? ' — ' + s.error : ''}${s.status ? ` (${s.status})` : ''}`);
    }

    if (res.ok) {
      log.info('run', `*** REGISTERED *** ${res.account.username} / ${res.account.email}`);
      notify.info(`registered: ${res.account.username} / ${res.account.email} / ${res.account.password}`);
      require('fs').writeFileSync(`${cfg.dataDir}/account.json`, JSON.stringify(res.account, null, 2));
    } else {
      log.error('run', `failed: ${res.error}`);
      notify.error(`registration failed: ${res.error}`);
      const arkoseStage = res.stages.find(s => s.stage === 'arkose');
      if (arkoseStage && arkoseStage.attempts) {
        for (const a of arkoseStage.attempts) log.warn('run', `  arkose attempt ${a.stage}: ${a.error || 'ok'}`);
      }
    }
    process.exit(res.ok ? 0 : 2);
  } catch (e) {
    log.critical('run', `crashed: ${e.message}`);
    notify.critical(`registration crashed: ${e.message}`);
    process.exit(1);
  }
})();
