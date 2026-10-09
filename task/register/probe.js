'use strict';
// thin proxy shim: reads /location through a proxy so the run is self-verifying
const https = require('https');
const http = require('http');
const { URL } = require('url');

const fetch = require('node-fetch');
const { HttpsProxyAgent } = require('https-proxy-agent');

async function check(proxyUrl) {
  const opts = { timeout: 15000 };
  if (proxyUrl) opts.agent = new HttpsProxyAgent(proxyUrl);
  const res = await fetch('https://api.ipify.org?format=json', opts);
  return { status: res.status, json: await res.json() };
}

module.exports = { check };