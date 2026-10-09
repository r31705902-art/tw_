// ---- shell policy ---------------------------------------------------------
// Near-unrestricted, as the operator asked. The only thing blocked is the
// irreducible floor — commands that destroy the workspace or the box itself.
// Everything reversible (npm, python, git, ssh, curl, bash scripts, compilers,
// package managers, arbitrary executables already on PATH) is allowed.
const path = require('path');

const BLOCKED = new Set([
  'rm', 'rmdir', 'del', 'erase', 'shred', 'dd', 'mkfs', 'mkfs.ext4', 'fdisk',
  'format', 'diskpart', 'wipefs', 'shutdown', 'reboot', 'poweroff', 'halt',
  'init', 'systemctl', 'kill', 'killall', 'pkill', 'taskkill',
  'bcdedit', 'reg', 'regedit', 'sc', 'net', 'netsh', 'cacls', 'icacls', 'chmod',
  'chown', 'fsutil', 'vssadmin', 'cipher', 'sdelete',
]);

// argument patterns that make an otherwise-allowed command destructive.
// NOTE: keep each pattern single-alternation. A top-level `|` splits the whole
// regex in JS — `/a|b/` matches "a" OR "b", not "a followed by b". The earlier
// version of this file read `/ > | >> \/(dev|…)/ ` and therefore blocked every
// command containing ">", which is why the agent stalled on ordinary redirects.
const BLOCKED_ARGS = [
  /\brm\s+(-[a-zA-Z]*[rf][a-zA-Z]*\s+)+(\/|~|\$HOME|\*|\.\.)/i,
  /\bdel\s+\/[sqf]/i,
  /\bformat\s+[a-z]:/i,
  /\bdd\s+.*of=\/dev\//i,
  /\btruncate\s+-s\s*0\s+\/dev\//i,
  /\bmkfs\b/i,
  /\bfdisk\b/i,
  /:\(\)\s*\{\s*:\|:&\s*\}/,                    // fork bomb
  />\s*\/dev\/(sd|nvme|disk)/i,                 // clobber a raw device
  />\s*\/etc\//i,                               // clobber /etc
  />\s*\/boot\//i,                              // clobber the bootloader
];

function checkCmd(parts) {
  const bin = path.basename(String(parts[0] || '')).toLowerCase();
  const base = bin.replace(/\.(exe|cmd|bat|com|ps1|sh|bash)$/i, '');
  if (BLOCKED.has(bin) || BLOCKED.has(base)) {
    throw new Error(`command blocked by policy: ${bin}`);
  }
  const line = parts.join(' ');
  const hit = BLOCKED_ARGS.find(rx => rx.test(line));
  if (hit) {
    throw new Error(`command blocked: destructive argument pattern (${hit})`);
  }
  return base;
}

module.exports = { checkCmd, BLOCKED, BLOCKED_ARGS };
