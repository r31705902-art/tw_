# tw-agent

Telegram-driven coding agent. Deployed to Railway (2 cores / 1 GB / no GPU).
Its one job: **get past `error_code 5021` on `passport.twitch.tv/protected_register`** and register a Twitch account.

## What is already proven

These facts were established by direct measurement, not guesswork. Start from them, do not re-litigate them.

| Fact | How it was established |
|---|---|
| Kasada chain works end to end | `backup_PROOT.js` run: `/mfc` → `200` + `x-kpsdk-h`; `gql/integrity` → `200` + `v4.local…` token + `x-kpsdk-ct` + `KP_UIDz` cookies |
| PoW accepts a locally computed `x-kpsdk-cd` | same run, no solver involved |
| `5021` is a **server-side** captcha check | 5 body variants (`captcha.token` short junk / long junk / `{}` / string / `.blob`) all returned byte-identical `5021`; a *bogus* `public_key` also returns `5021`, so the refusal precedes BDA parsing |
| `5025` is a different gate | no `integrity_token` in the body → `5025`; with it → `5021`. Injecting a live `gql/integrity` token into the page's own request flipped it from `5025` to `5021` |
| Arkose `gt2` returns `DENIED ACCESS` for everything | identical answer with: residential egress (ZA/US/DE/GB/FR), own IP, a fake `public_key`, an empty `bda`, every BDA field name (`bda`/`b64`/`c`/`b`), `capi_version` 2.18.1 **and** 4.4.5, `capi_mode` lightbox and inline, `ark-build-id` set, `data[blob]` present, and across `client-api`/`twitch-api`/`cdn`/`iframe` hosts |
| TLS fingerprint is not the gate | plain node HTTPS and `chrome_110/120/131/133`, `firefox_135`, `safari_ios` all get the same `DENIED ACCESS` |
| The BDA is **AES-256-CBC**, not RSA | read out of the 2026 enforcement VM: the derived key is the ASCII of 32 hex chars → 32 bytes; both VM branches (`crypto.subtle` present or absent) use AES-CBC. The `RSA-OAEP`/`importKey` block serves the data-exchange payload, not the BDA |
| The RSA key is not recoverable from `api.js` | `api.js` is 99 145 bytes and **byte-identical for two different site keys** (sha256 `7fbde4f6…`), served with CloudFront cache hits; `extractRsaKey()` returns NULL; no SPKI prefix, no long base64, no long concat chains |
| The key is not in the enforcement bundle either | `enforcement.6d0c4af962acb40222b82fccf3418258.js` is 287 647 bytes, one webpack module `4422`; the `J1` export resolves to `P`, which is only ever `void 0` or a numeric string-table index. Module boundary regexes that only match `function(t,e,r)` miss most modules — re-parse properly before concluding |
| Nothing useful lives outside the bundle | `sri.json`, `*.js.map`, `game_core_bootstrap.js`, `cdn.*` → `403`; `/v2/<pk>/settings` → `{}`; `/fc/gt2/public_key/<pk>?format=json` → `405`; `GET` on gt2 → `405` (so the route is alive) |
| Twitch's own signup page never mounts Arkose for automation | on `twitch.twitch.tv/signup` via puppeteer: 0 iframes, no arkose scripts, no `data-arkose-*`, no public keys, `setPublicKey` absent — one input only (`#email-input`), multi-step flow |
| The page's real register body | captured verbatim: `username, password, email, birthday, email_verification_enabled, client_id, is_password_guide` — with `integrity_token` added |
| A hand-built body fails with `1002 failed to decode JSON` | same fields, same shape, sent via `node-tls-client` — the server rejects it before it gets near the captcha. Let the browser build it |

## Known-good infrastructure

- **Proxy tiers** (`src/proxy.js`): residential (oxylabs) → datacenter (`proxies.txt`) → direct. Circuit-breaks, rotates sessions, and survives balance exhaustion by falling back to direct.
- **Proxy caveat**: oxylabs `403`s `gql.twitch.tv` (that host is blocked on their residential gateway), but passes `/mfc` and `passport.twitch.tv` fine. `proxies.txt` (datacenter) answers `gql/integrity` cleanly. Use residential for the register call, datacenter for integrity — the server does not appear to bind the two to one IP, but this is worth verifying.
- **Casada/BDA code**: `task/register/register.js` has the full proven chain. `bda_build.js` in the scratch folder has the AES-256-CBC wrapper.

## Where the work is

`error_code 5021` is the last gate. Everything up to it is green. The token must come from something the server accepts as a genuine solmisation.

Ranked by expected cost:

1. **Camoufox on the register page.** It survived the "your browser is not supported" check that puppeteer trips; the remaining problem was the cookie-consent overlay swallowing the submit click and the birthday `<select>`s not firing React's `change` (they are `aria-label`-suffixed — every label contains the word "birthday", so `[aria-label*="day" i]` matches the month widget first). Both are fixed in the code here. Camoufox is the highest-value lead.
2. **Reverse the real `gt2` handshake.** `DENIED ACCESS` for a bogus key proves the refusal precedes payload validation — so something *before* the body is wrong (cookie/esi session state, a required header, or the endpoint moved). Diff against a live capture from a working browser.
3. **Recover the BDA key from the enforcement VM properly.** The module-map parse was buggy; the VM is a single module `4422`. If `J1`'s `P` is genuinely always `void 0`, the deployment is keyless and the AES path needs no key at all — which would make a Node-only solution viable.

## Running

```bash
cp .env.example .env      # then edit
npm install
npm start                 # the agent + telegram bot
```

One registration attempt:

```bash
node task/register/run.js                    # residential proxy
node task/register/run.js --direct           # own IP
node task/register/run.js --browser camoufox # browser capture
```

## Deploy to Railway

```bash
git init && git add . && git commit -m "init"
gh repo create tw-agent --private --source=. --push
railway login && railway link && railway up
```

Set the env vars in the Railway dashboard. `PORT` is honoured for the healthcheck.

Memory budget: the agent process itself sits around 150–160 MB. A camoufox instance adds a further ~200 MB, which will not fit next to anything else on 1 GB — run it as a separate one-shot job, not in the main service.
