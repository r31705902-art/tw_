# artifacts/

Decompiled and reference scripts lifted from
`C:\Users\Rb\Desktop\projs\twitch-scp_sl-powder_toy\hzzzzz`.

These are raw working material — some of it obfuscated, some of it captured
traffic, some of it the reference implementations the mission is built on.
Nothing here is wired into `src/`; the agent reads them to learn the shapes.

## Layout

```
backup_PROOT.js      the current autoreg — full TLS session, Kasada PoW,
                     GQL integrity, then protected_register. The Kasada half
                     of this is proven working.
main.js, config.js, utils.js, trash-mail.js, follow.js   the masterking32
                     account creator (EXAAAAAAAAAAAAAMPLE/)
NLTAR/               puppeteer-with-fingerprints creator + node_modules —
                     only referenced, not copied wholesale
sessions/            captured session logs from earlier attempts
explain/, decomp/, PROT/   analysis notes, decompiled fragments, probes
B_HEEM/              unrelated shader work, kept for the archive
```

## What is worth reading first

1. `backup_PROOT.js` — the live autoreg. Steps 1 and 2 are green; step 3 is
   the Arkose hole the mission is about.
2. `sessions/get_arkose_enforcement.json` — the earlier analysis that named
   Twitch's Arkose public key `E5558E2B-…`.
3. `explain/arkose/` — decompiled Arkose fragments (api.js, enforcement frame).
4. `decomp/` — deobfuscated builds.

## Ground truth for the mission

- `api.js` served today (99 145 bytes) is byte-identical for two different site
  keys — a pure loader, no RSA material.
- The RSA key moved into `enforcement.<hash>.js`; that file is one webpack
  module `4422`, and the `J1` export it needs resolves to a numeric table
  index, not a key.
- `gt2` returns `DENIED ACCESS` for every payload shape and a fake public key
  alike — the refusal happens before payload parsing.
- The BDA the browser sends is AES-256-CBC, not RSA-wrapped.
