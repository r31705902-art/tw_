'use strict';
// The agent loop: tool-using, self-correcting, TG-notified.
//
// Works with native tool calling where available, and falls back to a
// ```json text protocol for gateways/models that do not expose tools.
const cfg = require('./config');
const log = require('./logger');
const notify = require('./notify');
const state = require('./state');
const llm = require('./llm');
const { runTool, schemas, bindAgent } = require('./tools');

const SYSTEM = `You are tw-agent, a coding agent on a small Railway box (2 cores, 1 GB RAM, no GPU).
Your mission is defined in TASK.md. Read it first, then work.

Notification policy — this is strict:
- Do NOT notify for routine work: tool calls, reads, edits, test runs, retries.
  Those go to the log only.
- You push to telegram ONLY through the notify tool, and only for:
  BREAKTHROUGH  — a real step forward (something new actually worked).
  WARNING       — a minor problem you are working around, worth a human glance.
  ERROR         — a hard stall, something you cannot solve yourself.
- Being stopped is never a reason to notify.
- Never pad, never echo the task back, never report "starting" or "finished".

Stopping:
- If you conclude the mission is impossible as specified, or you need a decision
  only the operator can make, call stop with an explicit reason. Say in one
  sentence what happened and what you need. Do not stop on a routine failure
  you can still work around.

Operating rules:
- You are autonomous. Diagnose from the log, form a hypothesis, test it, iterate.
- Never stall. Always end your turn with either a tool call or a written conclusion.
- Keep durable notes in NOTES.md as you go, so a restart loses nothing.
- HTTP only. No chromium, firefox, camoufox, puppeteer, or playwright in the
  final path — the operator may hand you a browser-captured token, but you never
  add a browser to the pipeline yourself.`;

class Agent {
  constructor(pool) {
    this.pool = pool;
    this.running = false;
    this.queue = [];
    this.current = null;
    this.controller = null;
    bindAgent(this);
  }

  submit(task, source = 'telegram') {
    this.queue.push({ task, source });
    log.info('agent', `queued task (${this.queue.length} pending) from ${source}`);
    return this.queue.length;
  }

  stop(reason) {
    this.running = false;
    this.stopReason = reason || 'no reason given';
    if (this.controller) { try { this.controller.abort(); } catch (e) { } }
    state.patch({ running: false, stopReason: this.stopReason });
    log.warn('agent', `stop requested: ${this.stopReason}`);
    // the operator stops the agent themselves, so no telegram ping here
  }

  stopSelf(reason) {
    log.warn('agent', `agent stopped itself: ${reason}`);
    this.stop(reason);
    notify.warn(`🛑 agent stopped itself — ${reason}`);
  }

  // Silence the noise on the loop: routine start/finish must not reach telegram.
  // Only genuine failures escalate. A self-stop reports itself (with the reason)
  // through stopSelf, and a real result only reaches the operator when the agent
  // explicitly asks for it with the notify tool.
  async start() {
    if (this.running) return false;
    this.running = true;
    state.patch({ running: true, startedAt: new Date().toISOString() });
    log.info('agent', 'started');
    this.loop().catch(e => {
      log.error('agent', `loop crashed: ${e.message}`);
      notify.critical(`agent loop crashed: ${e.message}`);
      this.running = false;
      state.patch({ running: false, lastError: e.message });
    });
    return true;
  }

  async loop() {
    while (this.running) {
      const item = this.queue.shift();
      if (!item) { await sleep(800); continue; }
      this.current = item;
      state.patch({ lastTask: item.task.slice(0, 400) });
      log.info('agent', `task from ${item.source}: ${item.task.slice(0, 300)}`);
      try {
        const result = await this.run(item.task);
        state.patch({ lastResult: String(result).slice(0, 2000), lastError: null });
        log.info('agent', `task done: ${String(result).slice(0, 200)}`);
      } catch (e) {
        state.patch({ lastError: e.message });
        // A transient gateway failure (429, reset socket) must not discard the
        // task — retry it a couple of times before declaring it dead.
        const transient = /429|ECONNRESET|ETIMEDOUT|cooldown|rate|timeout|socket hang up|fetch failed/i.test(e.message);
        if (transient && this.running && item.retries < 2) {
          item.retries = (item.retries || 0) + 1;
          log.warn('agent', `transient failure, retry ${item.retries}/2: ${e.message.slice(0, 90)}`);
          this.queue.unshift(item);
          await sleep(15000);
        } else {
          log.error('agent', `task failed: ${e.message}`);
          notify.error(`task failed: ${e.message}`);
        }
      } finally {
        this.current = null;
      }
    }
  }

  async run(task) {
    const s = state.load();
    const history = [{ role: 'system', content: SYSTEM }];
    if (Array.isArray(s.history)) history.push(...s.history);
    history.push({ role: 'user', content: task });

    let final = '';
    for (let turn = 0; turn < s.maxTurns; turn++) {
      if (!this.running) return `stopped after ${turn} turns`;
      s.turnsUsed++;
      state.patch({ turnsUsed: s.turnsUsed });

      const res = await llm.chat({ model: s.model, messages: history, tools: schemas });
      log.debug('agent', `turn ${turn} finish=${res.finish} tools=${res.toolCalls.length}`);

      let calls = res.toolCalls;
      if (!calls.length && res.text) {
        const fb = llm.parseToolFallback(res.text);
        if (fb.length) {
          log.debug('agent', `text-protocol fallback: ${fb.length} call(s)`);
          calls = fb;
        }
      }

      if (!calls.length) { final = res.text || '(empty)'; break; }

      history.push({ role: 'assistant', content: res.text || '', tool_calls: calls.map(c => ({ id: c.id, type: 'function', function: { name: c.name, arguments: c.argumentsText } })) });

      for (const call of calls) {
        let args = {};
        try { args = JSON.parse(call.argumentsText || '{}'); } catch (e) { }
        const label = `${call.name}(${JSON.stringify(args).slice(0, 120)})`;
        log.info('agent', `tool ${label}`);
        try {
          const out = await runTool(call.name, args);
          history.push({ role: 'tool', tool_call_id: call.id, name: call.name, content: out.slice(0, 12000) });
          log.debug('agent', `tool ok ${call.name} -> ${out.slice(0, 200)}`);
        } catch (e) {
          const msg = `tool error: ${e.message}`;
          history.push({ role: 'tool', tool_call_id: call.id, name: call.name, content: msg });
          // A tool failure is not an incident. The agent sees the error and
          // adapts on the next turn; notifying here floods telegram with the
          // agent's own trial-and-error, which is exactly what we do not want.
          log.warn('agent', `${call.name} -> ${e.message}`);
        }
      }

      if (turn === s.maxTurns - 1) {
        final = 'Reached max turns without a final answer.';
        notify.warn('agent hit max turns');
      }
    }

    state.patch({ history: history.filter(m => m.role !== 'system').slice(-40) });
    return final;
  }
}

const sleep = (ms) => new Promise(r => setTimeout(r, ms));
module.exports = { Agent, SYSTEM };
