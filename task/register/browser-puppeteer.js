'use strict';
// Optional browser token capture (puppeteer). `npm i puppeteer` to enable.
let cached = null;
function load() {
  if (cached !== null) return cached;
  try {
    const puppeteer = require('puppeteer');
    cached = { puppeteer, error: null };
  } catch (e) {
    cached = { error: e.message };
  }
  return cached;
}

async function capture({ proxy } = {}) {
  const m = load();
  if (m.error) throw new Error(`puppeteer not installed: ${m.error}`);

  const browser = await m.puppeteer.launch({
    headless: true,
    args: ['--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu', '--disable-gpu-compositing', '--disable-software-rasterizer'],
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
    for (let i = 0; i < 12 && !seen.length; i++) await new Promise(r => setTimeout(r, 5000));
    return seen[0] || null;
  } finally {
    await browser.close().catch(() => { });
  }
}

module.exports = { capture };