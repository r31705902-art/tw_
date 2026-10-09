'use strict';
// Wrapper around the arkose-solver package so the task code stays optional
// and the agent can swap the strategy without touching register.js.
let mod = null;
function load() {
  if (mod !== null) return mod;
  try {
    const pkg = require('arkose-solver');
    mod = {
      extractRsaKey: pkg.extractRsaKey || (() => ''),
      generateBda: pkg.generateBda,
      newSession: pkg.newSession,
      encrypt: pkg.encrypt,
      marshalBda: pkg.marshalBda,
    };
  } catch (e) {
    mod = { __error: e.message };
  }
  return mod;
}

module.exports = new Proxy({}, {
  get(_, prop) {
    const m = load();
    if (m.__error) throw new Error(`arkose-solver unavailable: ${m.__error} (npm i arkose-solver)`);
    const v = m[prop];
    if (typeof v === 'function') return v.bind(m);
    return v;
  },
});