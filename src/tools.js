'use strict';
// Sandboxed filesystem + allowlisted shell for the agent.
// Everything is rooted at cfg.workspaceDir; paths that escape throw.
const fs = require('fs');
const path = require('path');
const { execFile, spawn } = require('child_process');
const cfg = require('./config');
const log = require('./logger');
const notify = require('./notify');
const { checkCmd } = require('./cmdpolicy');

const ROOT = cfg.workspaceDir;

function resolveInside(p) {
  const rel = String(p || '.').replace(/^([a-zA-Z]):[\\/]/, '/');
  const abs = path.resolve(ROOT, rel);
  const normRoot = path.resolve(ROOT);
  if (abs !== normRoot && !abs.startsWith(normRoot + path.sep)) {
    throw new Error(`path escapes workspace: ${p}`);
  }
  return abs;
}

const tools = {
  read_file: {
    description: 'Read a text file inside the workspace. Supports offset/maxBytes to page through a large file.',
    parameters: {
      type: 'object',
      properties: {
        path: { type: 'string' },
        offset: { type: 'number' },
        maxBytes: { type: 'number' },
      },
      required: ['path'],
    },
    async run({ path: p, offset = 0, maxBytes = 200000 }) {
      const abs = resolveInside(p);
      const buf = fs.readFileSync(abs);
      const start = Math.max(0, Number(offset) || 0);
      const slice = buf.subarray(start, start + maxBytes);
      const text = slice.toString('utf8');
      const end = start + slice.length;
      const header = (start > 0 || end < buf.length)
        ? `[bytes ${start}-${end} of ${buf.length}] — pass offset:${end} to continue\n`
        : '';
      log.debug('tools', `read ${p} bytes ${start}-${end}/${buf.length}`);
      return header + text;
    },
  },

  write_file: {
    description: 'Write (create or overwrite) a file inside the workspace.',
    parameters: { type: 'object', properties: { path: { type: 'string' }, content: { type: 'string' } }, required: ['path', 'content'] },
    async run({ path: p, content }) {
      const abs = resolveInside(p);
      fs.mkdirSync(path.dirname(abs), { recursive: true });
      fs.writeFileSync(abs, String(content));
      log.info('tools', `wrote ${p} (${String(content).length}b)`);
      return `ok: ${p} (${String(content).length} bytes)`;
    },
  },

  replace_in_file: {
    description: 'Replace an exact substring in a file. Set all=true to replace every occurrence.',
    parameters: { type: 'object', properties: { path: { type: 'string' }, old: { type: 'string' }, new: { type: 'string' }, all: { type: 'boolean' } }, required: ['path', 'old', 'new'] },
    async run({ path: p, old: oldStr, new: newStr, all = false }) {
      const abs = resolveInside(p);
      const src = fs.readFileSync(abs, 'utf8');
      if (!src.includes(oldStr)) throw new Error(`substring not found in ${p}`);
      const count = all ? src.split(oldStr).length - 1 : 1;
      const out = all ? src.split(oldStr).join(newStr) : src.replace(oldStr, newStr);
      fs.writeFileSync(abs, out);
      log.info('tools', `edited ${p} (${count} replacement${count > 1 ? 's' : ''})`);
      return `ok: ${p} (${count} replaced)`;
    },
  },

  list_dir: {
    description: 'List files and directories inside the workspace. Pass a file path and you get its stat instead of an error.',
    parameters: { type: 'object', properties: { path: { type: 'string' }, depth: { type: 'number' } } },
    async run({ path: p = '.', depth = 2 }) {
      const abs = resolveInside(p);
      if (!fs.existsSync(abs)) return `no such path: ${p}`;
      const st = fs.statSync(abs);
      // pointed at a file: describe it instead of throwing ENOTDIR
      if (!st.isDirectory()) return `${p} is a file, ${st.size} bytes — use read_file for its contents`;
      const rows = [];
      const walk = (dir, d, prefix) => {
        for (const e of fs.readdirSync(dir, { withFileTypes: true }).sort((a, b) => a.name.localeCompare(b.name))) {
          const full = path.join(dir, e.name);
          const size = e.isDirectory() ? '' : ` ${fs.statSync(full).size}b`;
          rows.push(`${prefix}${e.name}${e.isDirectory() ? '/' : ''}${size}`);
          if (e.isDirectory() && d > 1 && !['node_modules', '.git', 'data'].includes(e.name)) walk(full, d - 1, prefix + '  ');
        }
      };
      walk(abs, Math.max(1, Math.min(6, depth)), '');
      return rows.slice(0, 2000).join('\n') || '(empty)';
    },
  },

  run_script: {
    description: 'Run a shell command (near-unrestricted: node, npm, python, git, ssh, curl, compilers, package managers, arbitrary executables on PATH). Only workspace/box destruction is blocked.',
    parameters: { type: 'object', properties: { cmd: { type: 'string' }, timeoutMs: { type: 'number' } }, required: ['cmd'] },
    async run({ cmd, timeoutMs }) {
      const timeout = Math.min(Number(timeoutMs || cfg.shell.timeoutMs), cfg.shell.maxTimeoutMs);
      const line = String(cmd).trim();
      // Shell metacharacters mean the command is a pipeline, not a single argv.
      // Splitting on whitespace there silently mangles `a; b`, `a | b`, `a > f`
      // — the agent writes those constantly, so honour them properly.
      const needsShell = /[;&|><`$(){}[\]*?!~]/.test(line) || /\s/.test(line.trim().split(/\s+/)[0] || '');
      const parts = line.split(/\s+/);
      checkCmd(parts);
      log.info('tools', `run: ${line.slice(0, 200)}`);
      return new Promise((resolve) => {
        const child = needsShell
          ? spawn(line, [], { cwd: ROOT, shell: true, env: process.env })
          : spawn(parts[0], parts.slice(1), { cwd: ROOT, shell: false, env: process.env });
        let out = '';
        let err = '';
        const kill = setTimeout(() => { try { child.kill('SIGKILL'); } catch (e) { } }, timeout);
        child.stdout.on('data', d => {
          out += d;
          if (out.length > cfg.shell.maxOutputBytes) { try { child.kill('SIGKILL'); } catch (e) { } }
        });
        child.stderr.on('data', d => { err += d; if (err.length > cfg.shell.maxOutputBytes) try { child.kill('SIGKILL'); } catch (e) { } });
        child.on('error', e => { clearTimeout(kill); resolve(`spawn error: ${e.message}`); });
        child.on('close', code => {
          clearTimeout(kill);
          resolve(`exit=${code}\n--- stdout ---\n${out.slice(0, cfg.shell.maxOutputBytes)}\n--- stderr ---\n${err.slice(0, cfg.shell.maxOutputBytes)}`);
        });
      });
    },
  },

  notify: {
    description: 'Send a message to the operator on telegram. Use ONLY for: breakthrough, warning, error. Never for routine work.',
    parameters: {
      type: 'object',
      properties: {
        level: { type: 'string', enum: ['breakthrough', 'warning', 'error'] },
        message: { type: 'string' },
      },
      required: ['level', 'message'],
    },
    async run({ level, message }) {
      const lvl = String(level || 'warning');
      log.info('tools', `notify[${lvl}] ${String(message).slice(0, 200)}`);
      const payload = [
        { breakthrough: '🎯 *BREAKTHROUGH*', warning: '⚠️ *WARNING*', error: '❌ *ERROR*' }[lvl] || '•',
        String(message).slice(0, 1500),
      ].join('\n');
      const ok = (notify.push && notify.push(payload)) || false;
      return ok ? 'sent' : 'telegram not configured; logged only';
    },
  },

  stop: {
    description: 'Stop yourself. Give an explicit reason. Use only when the mission is impossible as specified, or you need a decision only the operator can make. Never stop over a routine failure.',
    parameters: {
      type: 'object',
      properties: { reason: { type: 'string' } },
      required: ['reason'],
    },
    async run({ reason }) {
      const r = String(reason || '').trim();
      if (!r) throw new Error('a reason is required to stop');
      log.warn('tools', `stop requested with reason: ${r}`);
      const agent = holder.agent;
      if (agent && typeof agent.stopSelf === 'function') agent.stopSelf(r);
      return `stopping: ${r}`;
    },
  },
};

// openai-style tool schemas for providers with native tool calling
const schemas = Object.entries(tools).map(([name, t]) => ({
  type: 'function',
  function: { name, description: t.description, parameters: t.parameters },
}));

// late-bound so tools can reach the running agent without a circular import
// (stored on a holder object so it never leaks into the tool schemas)
const holder = { agent: null };
function bindAgent(agent) { holder.agent = agent; }

module.exports = {
  tools,
  schemas: Object.entries(tools).map(([name, t]) => ({
    type: 'function',
    function: { name, description: t.description, parameters: t.parameters },
  })),
  bindAgent,
  runTool: async (name, args) => {
    const t = tools[name];
    if (!t) throw new Error(`unknown tool: ${name}`);
    return String(await t.run(args || {}));
  },
};
