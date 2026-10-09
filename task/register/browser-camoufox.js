'use strict';
// Optional browser token capture (camoufox). Not installed by default —
// `npm i camoufox` and the task code will pick it up automatically.
let cached = null;
function load() {
  if (cached !== null) return cached;
  try {
    const { Camoufox } = require('camoufox');
    cached = { Camoufox, error: null };
  } catch (e) {
    cached = { error: e.message };
  }
  return cached;
}

async function capture({ proxy } = {}) {
  const m = load();
  if (m.error) throw new Error(`camoufox not installed: ${m.error}`);

  const browser = await m.Camoufox({
    headless: true,
    os: 'windows',
    geoip: true,
    block_images: false,
    ...(proxy && proxy.url ? { proxy: { server: proxy.url } } : {}),
  });
  try {
    const page = await browser.newPage();
    const seen = [];
    page.on('response', async (r) => {
      const u = r.url();
      if (!/arkoselabs|funcaptcha/.test(u)) return;
      const body = await r.text().catch(() => '');
      const m2 = /"token"\s*:\s*"([^"]{40,})"/.exec(body);
      if (m2) seen.push(m2[1]);
    });
    await page.goto('https://www.twitch.tv/signup', { waitUntil: 'domcontentloaded', timeout: 90000 });
    // let the challenge mount
    for (let i = 0; i < 12 && !seen.length; i++) await new Promise(r => setTimeout(r, 5000));
    return seen[0] || null;
  } finally {
    await browser.close().catch(() => { });
  }
}

module.exports = { capture };