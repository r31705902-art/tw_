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

// argument patterns that make an otherwise-allowed command destructive
const BLOCKED_ARGS = [
  /\brm\s+(-[a-zA-Z]*[rf][a-zA-Z]*\s+)+(\/|~|\$HOME|\*|\.\.)/i,
  /\brm\s+-rf?\s+\S+\s+\*/i,
  /\bdel\s+\/[sqf]/i,
  /\bformat\s+[a-z]:/i,
  /\bdd\s+.*of=\/dev\//i,
  /:\(\)\s*\{\s*:\|:&\s*\}/,                                  // fork bomb
  /\>|\>\>\s*\/(dev|etc|proc|sys|boot)/i,                     // clobber system dirs
];

function checkCmd(parts) {
  const bin = path.basename(String(parts[0] || '')).toLowerCase();
  const base = bin.replace(/\.(exe|cmd|bat|com|ps1|sh|bash)$/i, '');
  if (BLOCKED.has(bin) || BLOCKED.has(base)) {
    throw new Error(`command blocked by policy: ${bin}`);
  }
  const line = parts.join(' ');
  if (BLOCKED_ARGS.some(rx => rx.test(line))) {
    throw new Error('command blocked: destructive argument pattern');
  }
  return base;
}

module.exports = { checkCmd, BLOCKED, BLOCKED_ARGS };
