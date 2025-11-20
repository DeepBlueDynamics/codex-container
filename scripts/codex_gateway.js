#!/usr/bin/env node
const http = require('http');
const { spawn } = require('child_process');
const fs = require('fs');
const fsp = fs.promises;
const path = require('path');
const crypto = require('crypto');
const { URL } = require('url');
const EventEmitter = require('events');

const DEFAULT_PORT = parseInt(process.env.CODEX_GATEWAY_PORT || '4000', 10);
const DEFAULT_HOST = process.env.CODEX_GATEWAY_BIND || '0.0.0.0';
const DEFAULT_TIMEOUT_MS = parseInt(process.env.CODEX_GATEWAY_TIMEOUT_MS || '120000', 10);
const DEFAULT_IDLE_TIMEOUT_MS = parseInt(process.env.CODEX_GATEWAY_IDLE_TIMEOUT_MS || '900000', 10);
const MAX_TIMEOUT_MS = parseInt(process.env.CODEX_GATEWAY_MAX_TIMEOUT_MS || '1800000', 10); // 30 minutes
const DEFAULT_MODEL = process.env.CODEX_GATEWAY_DEFAULT_MODEL || '';
const EXTRA_ARGS = (process.env.CODEX_GATEWAY_EXTRA_ARGS || '')
  .split(/\s+/)
  .filter(Boolean);
const SESSION_DIR = process.env.CODEX_GATEWAY_SESSION_DIR
  || path.join(process.cwd(), '.codex-gateway-sessions');
const MAX_BODY_BYTES = parseInt(process.env.CODEX_GATEWAY_MAX_BODY_BYTES || '1048576', 10);
const DEFAULT_TAIL_LINES = parseInt(process.env.CODEX_GATEWAY_DEFAULT_TAIL_LINES || '200', 10);
const MAX_TAIL_LINES = parseInt(process.env.CODEX_GATEWAY_MAX_TAIL_LINES || '2000', 10);
const SIGNAL_CONTEXT_CHARS = parseInt(process.env.CODEX_GATEWAY_SIGNAL_CONTEXT || '160', 10);

function ensureDirSync(dir) {
  if (!fs.existsSync(dir)) {
    fs.mkdirSync(dir, { recursive: true });
  }
}

function clampNumber(value, min, max) {
  if (typeof value !== 'number' || Number.isNaN(value)) {
    return min;
  }
  return Math.min(Math.max(value, min), max);
}

function safeJsonParse(body) {
  try {
    return { ok: true, value: JSON.parse(body) };
  } catch (error) {
    return { ok: false, error };
  }
}

function sendJson(res, statusCode, payload) {
  const body = JSON.stringify(payload);
  res.writeHead(statusCode, {
    'Content-Type': 'application/json',
    'Content-Length': Buffer.byteLength(body),
  });
  res.end(body);
}

function sendError(res, statusCode, message, extra = {}) {
  sendJson(res, statusCode, { error: message, ...extra });
}

function readBody(req) {
  return new Promise((resolve, reject) => {
    let body = '';
    req.on('data', (chunk) => {
      body += chunk.toString();
      if (body.length > MAX_BODY_BYTES) {
        reject(new Error('Payload too large'));
      }
    });
    req.on('error', (err) => reject(err));
    req.on('end', () => resolve(body));
  });
}

function sanitizeEnv(envPayload) {
  if (!envPayload || typeof envPayload !== 'object') {
    return null;
  }
  const result = {};
  for (const [key, value] of Object.entries(envPayload)) {
    if (typeof key !== 'string' || key.trim().length === 0) {
      continue;
    }
    if (typeof value !== 'string') {
      continue;
    }
    result[key.toUpperCase()] = value;
  }
  return Object.keys(result).length > 0 ? result : null;
}

function buildPrompt(messages, systemPrompt) {
  const parts = [];
  if (systemPrompt && systemPrompt.trim().length > 0) {
    parts.push(`System:\n${systemPrompt.trim()}`);
  }
  for (const msg of messages) {
    if (!msg || typeof msg.content !== 'string') {
      continue;
    }
    const role = (msg.role || 'user').toLowerCase();
    const prefix = role === 'assistant' ? 'Assistant' : role === 'system' ? 'System' : 'User';
    parts.push(`${prefix}:\n${msg.content.trim()}`);
  }
  parts.push('Assistant:');
  return parts.join('\n\n');
}

function extractPromptPreview(messages, systemPrompt) {
  const text = buildPrompt(messages, systemPrompt);
  return text.slice(0, 400);
}

function extractCodexSessionId(events) {
  if (!Array.isArray(events)) {
    return null;
  }
  for (const entry of events) {
    if (!entry || typeof entry !== 'object') {
      continue;
    }
    const msg = entry.msg;
    if (!msg) {
      continue;
    }
    if (typeof msg.session_id === 'string' && msg.session_id.trim().length > 0) {
      return msg.session_id.trim();
    }
    if (msg.session && typeof msg.session.id === 'string' && msg.session.id.trim().length > 0) {
      return msg.session.id.trim();
    }
  }
  return null;
}

function parseTailParam(url) {
  const raw = url.searchParams.get('tail');
  if (!raw) {
    return DEFAULT_TAIL_LINES;
  }
  const parsed = parseInt(raw, 10);
  if (Number.isNaN(parsed) || parsed <= 0) {
    return DEFAULT_TAIL_LINES;
  }
  return Math.min(parsed, MAX_TAIL_LINES);
}

function parseBoolean(value) {
  if (typeof value === 'boolean') {
    return value;
  }
  if (typeof value === 'string') {
    return ['1', 'true', 'yes', 'on'].includes(value.toLowerCase());
  }
  return false;
}

class SessionStore {
  constructor(rootDir) {
    this.rootDir = rootDir;
    ensureDirSync(this.rootDir);
    this.sessions = new Map();
    this.codexIndex = new Map();
    this.ready = this.loadExisting();
  }

  async loadExisting() {
    try {
      const entries = await fsp.readdir(this.rootDir, { withFileTypes: true });
      for (const entry of entries) {
        if (!entry.isDirectory() || !entry.name.startsWith('session-')) {
          continue;
        }
        const sessionId = entry.name.replace(/^session-/, '');
        const metaPath = this.metaPath(sessionId);
        try {
          const metaRaw = await fsp.readFile(metaPath, 'utf8');
          const meta = JSON.parse(metaRaw);
          if (meta && meta.session_id) {
            this.sessions.set(meta.session_id, meta);
            if (meta.codex_session_id) {
              this.codexIndex.set(meta.codex_session_id, meta.session_id);
            }
          }
        } catch (error) {
          console.error(`[codex-gateway] failed to load session ${sessionId}:`, error.message);
        }
      }
    } catch (error) {
      console.error('[codex-gateway] unable to load sessions:', error.message);
    }
  }

  sessionDir(sessionId) {
    return path.join(this.rootDir, `session-${sessionId}`);
  }

  metaPath(sessionId) {
    return path.join(this.sessionDir(sessionId), 'meta.json');
  }

  stdoutPath(sessionId) {
    return path.join(this.sessionDir(sessionId), 'stdout.log');
  }

  stderrPath(sessionId) {
    return path.join(this.sessionDir(sessionId), 'stderr.log');
  }

  eventsPath(sessionId) {
    return path.join(this.sessionDir(sessionId), 'events.jsonl');
  }

  async createSession(seedMeta = {}) {
    const sessionId = crypto.randomUUID();
    const now = new Date().toISOString();
    const meta = {
      session_id: sessionId,
      codex_session_id: seedMeta.codex_session_id || null,
      created_at: now,
      updated_at: now,
      last_activity_at: now,
      status: 'idle',
      model: seedMeta.model || DEFAULT_MODEL || null,
      objective: seedMeta.objective || '',
      nudge_prompt: seedMeta.nudge_prompt || '',
      nudge_interval_ms: seedMeta.nudge_interval_ms || null,
      worker_state: 'stopped',
      worker_pid: null,
      execution_timeout_ms: seedMeta.execution_timeout_ms || DEFAULT_TIMEOUT_MS,
      idle_timeout_ms: seedMeta.idle_timeout_ms || DEFAULT_IDLE_TIMEOUT_MS,
      runs: [],
    };
    this.sessions.set(sessionId, meta);
    ensureDirSync(this.sessionDir(sessionId));
    await Promise.all([
      fsp.writeFile(this.stdoutPath(sessionId), '', 'utf8'),
      fsp.writeFile(this.stderrPath(sessionId), '', 'utf8'),
      fsp.writeFile(this.eventsPath(sessionId), '', 'utf8'),
    ]);
    await this.saveMeta(sessionId);
    return sessionId;
  }

  resolveSessionId(identifier) {
    if (!identifier) {
      return null;
    }
    if (this.sessions.has(identifier)) {
      return identifier;
    }
    if (this.codexIndex.has(identifier)) {
      return this.codexIndex.get(identifier);
    }
    return null;
  }

  async beginRun({ sessionId, metadata }) {
    let resolved = sessionId;
    if (resolved) {
      if (!this.sessions.has(resolved)) {
        throw new Error(`Session '${sessionId}' not found`);
      }
    } else {
      resolved = await this.createSession(metadata);
    }

    const meta = this.sessions.get(resolved);
    const runId = crypto.randomUUID();
    const now = new Date().toISOString();
    const runRecord = {
      run_id: runId,
      status: 'running',
      started_at: now,
      prompt_preview: metadata.prompt_preview || '',
      timeout_ms: metadata.timeout_ms || null,
      resume_session_id: metadata.resume_codex_session_id || null,
    };
    meta.runs = Array.isArray(meta.runs) ? meta.runs : [];
    meta.runs.push(runRecord);
    meta.status = 'running';
    meta.last_activity_at = now;
    if (metadata.model) {
      meta.model = metadata.model;
    }
    if (metadata.timeout_ms) {
      meta.execution_timeout_ms = metadata.timeout_ms;
    }
    if (metadata.idle_timeout_ms) {
      meta.idle_timeout_ms = metadata.idle_timeout_ms;
    }
    if (metadata.objective && !meta.objective) {
      meta.objective = metadata.objective;
    }
    if (metadata.nudge_prompt) {
      meta.nudge_prompt = metadata.nudge_prompt;
    }
    if (metadata.nudge_interval_ms) {
      meta.nudge_interval_ms = metadata.nudge_interval_ms;
    }
    await this.saveMeta(resolved);
    await this.appendStdout(resolved, `\n\n===== RUN ${runId} START ${now} =====\n`);
    return { sessionId: resolved, runId, meta: JSON.parse(JSON.stringify(meta)) };
  }

  async appendStdout(sessionId, chunk) {
    if (!chunk) {
      return;
    }
    const file = this.stdoutPath(sessionId);
    const meta = this.sessions.get(sessionId);
    if (meta) {
      meta.last_activity_at = new Date().toISOString();
    }
    try {
      await fsp.appendFile(file, chunk);
    } catch (error) {
      console.error('[codex-gateway] failed to append stdout:', error.message);
    }
  }

  async appendStderr(sessionId, chunk) {
    if (!chunk) {
      return;
    }
    const file = this.stderrPath(sessionId);
    try {
      await fsp.appendFile(file, chunk);
    } catch (error) {
      console.error('[codex-gateway] failed to append stderr:', error.message);
    }
  }

  async appendEvents(sessionId, events, runId) {
    if (!Array.isArray(events) || events.length === 0) {
      return;
    }
    const payload = events
      .map((event) => JSON.stringify({ ...event, run_id: runId }))
      .join('\n');
    try {
      await fsp.appendFile(this.eventsPath(sessionId), `${payload}\n`);
    } catch (error) {
      console.error('[codex-gateway] failed to append events:', error.message);
    }
  }

  async finishRun(sessionId, runId, payload) {
    const meta = this.sessions.get(sessionId);
    if (!meta) {
      return;
    }
    const run = Array.isArray(meta.runs)
      ? meta.runs.find((entry) => entry.run_id === runId)
      : null;
    const now = new Date().toISOString();
    if (run) {
      run.status = payload.status || 'completed';
      run.completed_at = now;
      if (run.started_at) {
        run.duration_ms = Date.now() - Date.parse(run.started_at);
      }
      if (payload.error) {
        run.error = payload.error;
      }
      if (payload.content) {
        run.content_preview = String(payload.content).slice(0, 400);
      }
    }
    if (payload.codexSessionId) {
      meta.codex_session_id = payload.codexSessionId;
      this.codexIndex.set(payload.codexSessionId, sessionId);
    }
    meta.status = payload.status === 'completed' ? 'idle' : payload.status || meta.status;
    meta.last_activity_at = now;
    await this.appendStdout(sessionId, `\n===== RUN ${runId} END ${now} [${meta.status}] =====\n`);
    await this.saveMeta(sessionId);
    if (payload.events) {
      await this.appendEvents(sessionId, payload.events, runId);
    }
  }

  async setWorkerState(sessionId, state, extra = {}) {
    const meta = this.sessions.get(sessionId);
    if (!meta) {
      return;
    }
    meta.worker_state = state;
    if (Object.prototype.hasOwnProperty.call(extra, 'worker_pid')) {
      meta.worker_pid = extra.worker_pid;
    }
    if (extra.last_activity_at) {
      meta.last_activity_at = extra.last_activity_at;
    }
    if (extra.codex_session_id) {
      meta.codex_session_id = extra.codex_session_id;
      this.codexIndex.set(extra.codex_session_id, sessionId);
    }
    await this.saveMeta(sessionId);
  }

  async listSessions(limit) {
    const entries = Array.from(this.sessions.values());
    entries.sort((a, b) => {
      const left = Date.parse(b.updated_at || b.created_at || 0);
      const right = Date.parse(a.updated_at || a.created_at || 0);
      return left - right;
    });
    const sliced = typeof limit === 'number' && limit > 0 ? entries.slice(0, limit) : entries;
    return sliced.map((meta) => ({
      session_id: meta.session_id,
      codex_session_id: meta.codex_session_id,
      status: meta.status,
      created_at: meta.created_at,
      updated_at: meta.updated_at,
      last_activity_at: meta.last_activity_at,
      model: meta.model,
      objective: meta.objective,
      worker_state: meta.worker_state || 'stopped',
      worker_pid: Object.prototype.hasOwnProperty.call(meta, 'worker_pid') ? meta.worker_pid : null,
      execution_timeout_ms: meta.execution_timeout_ms || DEFAULT_TIMEOUT_MS,
      idle_timeout_ms: meta.idle_timeout_ms || DEFAULT_IDLE_TIMEOUT_MS,
      runs: Array.isArray(meta.runs) ? meta.runs.length : 0,
    }));
  }

  async getMeta(sessionId) {
    const meta = this.sessions.get(sessionId);
    return meta ? JSON.parse(JSON.stringify(meta)) : null;
  }

  async saveMeta(sessionId) {
    const meta = this.sessions.get(sessionId);
    if (!meta) {
      return;
    }
    meta.updated_at = new Date().toISOString();
    if (meta.codex_session_id) {
      this.codexIndex.set(meta.codex_session_id, sessionId);
    }
    await fsp.writeFile(this.metaPath(sessionId), `${JSON.stringify(meta, null, 2)}\n`, 'utf8');
  }

  async readTail(sessionId, fileName, lineLimit) {
    const filePath = path.join(this.sessionDir(sessionId), fileName);
    try {
      const data = await fsp.readFile(filePath, 'utf8');
      if (!lineLimit || lineLimit <= 0) {
        return data;
      }
      const lines = data.split(/\r?\n/);
      return lines.slice(-lineLimit).join('\n');
    } catch (error) {
      if (error.code === 'ENOENT') {
        return '';
      }
      throw error;
    }
  }

  async searchSession(sessionId, query, options = {}) {
    const filePath = this.stdoutPath(sessionId);
    let text = '';
    try {
      text = await fsp.readFile(filePath, 'utf8');
    } catch (error) {
      if (error.code === 'ENOENT') {
        return [];
      }
      throw error;
    }
    const lowerText = text.toLowerCase();
    const searchLower = query.toLowerCase();
    const maxResults = options.maxResults || 5;
    const matches = [];

    if (!options.fuzzy) {
      let index = lowerText.indexOf(searchLower);
      while (index !== -1 && matches.length < maxResults) {
        const start = Math.max(0, index - SIGNAL_CONTEXT_CHARS);
        const end = Math.min(text.length, index + searchLower.length + SIGNAL_CONTEXT_CHARS);
        matches.push({
          match_id: `${sessionId}-${index}-${matches.length}`,
          signal_type: 'text_match',
          score: 1,
          start,
          end: index + searchLower.length,
          window_start: start,
          window_end: end,
          snippet: text.slice(start, end),
        });
        index = lowerText.indexOf(searchLower, index + searchLower.length);
      }
      return matches;
    }

    const queryTokens = searchLower.split(/\s+/).filter(Boolean);
    if (queryTokens.length === 0) {
      return [];
    }
    const querySet = new Set(queryTokens);
    const segments = text.split(/\n+/);
    let offset = 0;
    for (const segment of segments) {
      const segmentLower = segment.toLowerCase();
      const segmentTokens = segmentLower.split(/\s+/).filter(Boolean);
      const segmentSet = new Set(segmentTokens);
      let overlap = 0;
      for (const token of querySet) {
        if (segmentSet.has(token)) {
          overlap += 1;
        }
      }
      const score = overlap / querySet.size;
      if (score >= (options.minScore || 0.34)) {
        const start = offset;
        const end = offset + segment.length;
        matches.push({
          match_id: `${sessionId}-fuzzy-${matches.length}`,
          signal_type: 'fuzzy_text_hit',
          score,
          start,
          end,
          window_start: start,
          window_end: end,
          snippet: segment.trim().slice(0, SIGNAL_CONTEXT_CHARS * 2),
        });
      }
      offset += segment.length + 1;
      if (matches.length >= maxResults) {
        break;
      }
    }
    return matches;
  }
}

const sessionStore = new SessionStore(SESSION_DIR);
const workerPool = new Map();

class SessionWorker extends EventEmitter {
  constructor(sessionId, store, options = {}) {
    super();
    this.sessionId = sessionId;
    this.store = store;
    this.options = options;
    this.proc = null;
    this.stdoutBuffer = '';
    this.currentRun = null;
    this.codexSessionId = options.codexSessionId || null;
    this.idleTimer = null;
    this.starting = null;
    this.startOptions = null;
  }

  buildArgs(meta) {
    const args = ['shell', '--json', '--color=never', '--skip-git-repo-check'];
    if (meta && meta.model) {
      args.push('--model', meta.model);
    }
    if (meta && meta.codex_session_id) {
      args.push('resume', meta.codex_session_id);
    }
    return args;
  }

  scheduleIdleTimer(timeoutMs) {
    this.clearIdleTimer();
    if (!timeoutMs || timeoutMs <= 0) {
      return;
    }
    this.idleTimer = setTimeout(() => {
      this.stop('idle_timeout');
    }, timeoutMs);
  }

  clearIdleTimer() {
    if (this.idleTimer) {
      clearTimeout(this.idleTimer);
      this.idleTimer = null;
    }
  }

  async start(options = {}) {
    if (this.proc) {
      return;
    }
    if (this.starting) {
      await this.starting;
      return;
    }
    const mergedEnv = { ...(this.options.env || {}), ...(options.env || {}) };
    this.options = { ...this.options, ...options, env: mergedEnv };
    const meta = await this.store.getMeta(this.sessionId);
    if (meta && meta.codex_session_id) {
      this.codexSessionId = meta.codex_session_id;
    }
    const spawnOptions = {
      cwd: this.options.cwd || meta?.cwd || process.cwd(),
      env: {
        ...process.env,
        ...(this.options.env || {}),
      },
      stdio: ['pipe', 'pipe', 'pipe'],
    };
    this.startOptions = spawnOptions;
    this.starting = new Promise((resolve, reject) => {
      const args = this.buildArgs(meta || {});
      const child = spawn('codex', args, spawnOptions);
      this.proc = child;
      this.store.setWorkerState(this.sessionId, 'starting', { worker_pid: child.pid });
      child.stdout.on('data', (chunk) => this.handleStdout(chunk));
      child.stderr.on('data', (chunk) => this.handleStderr(chunk));
      child.on('error', (error) => {
        console.error('[codex-gateway] worker error:', error);
        this.finishCurrentRun('error', { error: error.message });
        this.proc = null;
        this.store.setWorkerState(this.sessionId, 'stopped', { worker_pid: null });
        workerPool.delete(this.sessionId);
        reject(error);
      });
      child.on('close', (code, signal) => {
        this.proc = null;
        this.finishCurrentRun('error', {
          error: `Worker exited (${signal || code || 'unknown'})`,
        });
        this.store.setWorkerState(this.sessionId, 'stopped', { worker_pid: null });
        this.clearIdleTimer();
        workerPool.delete(this.sessionId);
        this.emit('exit', { code, signal });
      });
      child.once('spawn', () => {
        this.store.setWorkerState(this.sessionId, 'idle', { worker_pid: child.pid });
        this.scheduleIdleTimer(this.options.idleTimeoutMs || meta?.idle_timeout_ms || DEFAULT_IDLE_TIMEOUT_MS);
        resolve();
      });
    });
    await this.starting;
    this.starting = null;
  }

  handleStdout(chunk) {
    const text = chunk.toString();
    this.store.appendStdout(this.sessionId, text);
    this.stdoutBuffer += text;
    let index = this.stdoutBuffer.indexOf('\n');
    while (index !== -1) {
      const line = this.stdoutBuffer.slice(0, index).trim();
      this.stdoutBuffer = this.stdoutBuffer.slice(index + 1);
      if (line.length > 0) {
        this.processEventLine(line);
      }
      index = this.stdoutBuffer.indexOf('\n');
    }
  }

  handleStderr(chunk) {
    this.store.appendStderr(this.sessionId, chunk.toString());
  }

  processEventLine(line) {
    let parsed;
    try {
      parsed = JSON.parse(line);
    } catch (error) {
      return;
    }
    const eventSessionId = parsed.session_id
      || parsed.session?.id
      || (parsed.msg && (parsed.msg.session_id || parsed.msg.session?.id));
    if (eventSessionId && eventSessionId !== this.codexSessionId) {
      this.codexSessionId = eventSessionId;
      this.store.setWorkerState(this.sessionId, this.proc ? (this.currentRun ? 'running' : 'idle') : 'stopped', {
        codex_session_id: eventSessionId,
        worker_pid: this.proc ? this.proc.pid : null,
      });
    }
    if (this.currentRun) {
      this.currentRun.events.push(parsed);
      if (parsed.msg) {
        switch (parsed.msg.type) {
          case 'agent_message':
            if (typeof parsed.msg.message === 'string') {
              this.currentRun.content = parsed.msg.message;
            }
            break;
          case 'task_complete':
            if (typeof parsed.msg.last_agent_message === 'string') {
              this.currentRun.content = parsed.msg.last_agent_message;
            }
            this.finishCurrentRun('completed');
            return;
          case 'mcp_tool_call_begin':
          case 'mcp_tool_call_end':
            this.currentRun.toolCalls.push(parsed.msg);
            break;
          default:
            break;
        }
      }
      if (parsed.type === 'turn.completed') {
        this.finishCurrentRun('completed');
      }
    }
  }

  async sendPrompt({ messages, systemPrompt, timeoutMs, promptPreview }) {
    await this.start();
    if (this.currentRun) {
      throw new Error('Session worker is busy');
    }
    this.clearIdleTimer();
    this.store.setWorkerState(this.sessionId, 'running', { worker_pid: this.proc ? this.proc.pid : null });
    const input = buildPrompt(messages, systemPrompt);
    return new Promise((resolve, reject) => {
      const timer = timeoutMs ? setTimeout(() => {
        this.finishCurrentRun('timeout', { error: `Timed out after ${timeoutMs}ms` });
        this.stop('timeout');
      }, timeoutMs) : null;
      this.currentRun = {
        resolve,
        reject,
        events: [],
        content: '',
        toolCalls: [],
        promptPreview,
        timer,
      };
      try {
        const payload = input.endsWith('\n') ? input : `${input}\n`;
        this.proc.stdin.write(`${payload}\n`);
      } catch (error) {
        if (timer) {
          clearTimeout(timer);
        }
        this.currentRun = null;
        reject(error);
      }
    });
  }

  finishCurrentRun(status, extra = {}) {
    if (!this.currentRun) {
      return;
    }
    if (this.currentRun.timer) {
      clearTimeout(this.currentRun.timer);
    }
    const result = {
      status,
      content: this.currentRun.content,
      tool_calls: this.currentRun.toolCalls,
      events: this.currentRun.events,
      codex_session_id: this.codexSessionId,
    };
    if (extra.error) {
      result.error = extra.error;
    }
    const resolver = status === 'completed' ? this.currentRun.resolve : this.currentRun.reject;
    this.currentRun = null;
    if (resolver) {
      resolver(result);
    }
    if (this.proc) {
      this.store.setWorkerState(this.sessionId, 'idle', { worker_pid: this.proc.pid });
      this.scheduleIdleTimer(this.options.idleTimeoutMs || DEFAULT_IDLE_TIMEOUT_MS);
    }
  }

  async stop(reason = 'stopped') {
    this.clearIdleTimer();
    if (this.proc) {
      try {
        this.proc.kill('SIGTERM');
      } catch (error) {
        console.error('[codex-gateway] failed to stop worker:', error.message);
      }
    }
    await this.store.setWorkerState(this.sessionId, 'stopped', {
      worker_pid: null,
    });
  }
}

async function ensureSessionWorker(sessionId, options = {}) {
  let worker = workerPool.get(sessionId);
  if (!worker) {
    worker = new SessionWorker(sessionId, sessionStore, options);
    workerPool.set(sessionId, worker);
  }
  await worker.start(options);
  return worker;
}

function buildRunOptions(payload, meta) {
  const timeoutCandidate = typeof payload.timeout_ms === 'number'
    ? payload.timeout_ms
    : typeof payload.max_duration_ms === 'number'
      ? payload.max_duration_ms
      : DEFAULT_TIMEOUT_MS;
  const timeoutMs = clampNumber(timeoutCandidate, 5000, MAX_TIMEOUT_MS);
  const cwdCandidate = typeof payload.cwd === 'string' && payload.cwd.trim().length > 0
    ? payload.cwd
    : process.cwd();
  const envVars = sanitizeEnv(payload.env);
  return {
    timeoutMs,
    cwd: cwdCandidate,
    env: envVars,
    model: typeof payload.model === 'string' && payload.model.trim().length > 0
      ? payload.model.trim()
      : DEFAULT_MODEL,
    objective: typeof payload.objective === 'string' ? payload.objective.trim() : '',
    nudge_prompt: typeof payload.nudge_prompt === 'string' ? payload.nudge_prompt.trim() : '',
    nudge_interval_ms: typeof payload.nudge_interval_ms === 'number'
      ? clampNumber(payload.nudge_interval_ms, 60000, MAX_TIMEOUT_MS)
      : null,
    prompt_preview: typeof meta.prompt_preview === 'string' ? meta.prompt_preview : '',
    idle_timeout_ms: typeof payload.idle_timeout_ms === 'number'
      ? clampNumber(payload.idle_timeout_ms, 60000, MAX_TIMEOUT_MS)
      : DEFAULT_IDLE_TIMEOUT_MS,
  };
}

function runCodex(prompt, model, options = {}) {
  return new Promise((resolve, reject) => {
    const args = ['exec', '--json', '--color=never', '--skip-git-repo-check'];
    if (model) {
      args.push('--model', model);
    }
    if (Array.isArray(EXTRA_ARGS) && EXTRA_ARGS.length > 0) {
      args.push(...EXTRA_ARGS);
    }
    if (options.resumeSessionId) {
      args.push('resume', options.resumeSessionId);
    }
    args.push('-');

    const cwd = options.cwd || process.cwd();
    const timeoutMs = options.timeoutMs || DEFAULT_TIMEOUT_MS;
    const env = { ...process.env };
    if (options.env && typeof options.env === 'object') {
      for (const [key, value] of Object.entries(options.env)) {
        env[key] = value;
      }
    }

    const proc = spawn('codex', args, {
      cwd,
      env,
      stdio: ['pipe', 'pipe', 'pipe'],
    });

    let stdout = '';
    let stderr = '';
    let finished = false;

    const timer = setTimeout(() => {
      if (!finished) {
        finished = true;
        proc.kill('SIGTERM');
        reject(new Error(`Codex exec timed out after ${timeoutMs}ms`));
      }
    }, timeoutMs);

    proc.stdout.on('data', (chunk) => {
      const text = chunk.toString();
      stdout += text;
      if (typeof options.onStdout === 'function') {
        try {
          options.onStdout(text);
        } catch (error) {
          console.error('[codex-gateway] onStdout handler failed:', error.message);
        }
      }
    });

    proc.stderr.on('data', (chunk) => {
      const text = chunk.toString();
      stderr += text;
      if (typeof options.onStderr === 'function') {
        try {
          options.onStderr(text);
        } catch (error) {
          console.error('[codex-gateway] onStderr handler failed:', error.message);
        }
      }
    });

    proc.on('error', (error) => {
      if (!finished) {
        finished = true;
        clearTimeout(timer);
        reject(error);
      }
    });

    proc.on('close', (code) => {
      if (finished) {
        return;
      }
      finished = true;
      clearTimeout(timer);
      if (code !== 0) {
        const message = stderr || stdout || `Codex exited with code ${code}`;
        reject(new Error(message.trim()));
        return;
      }
      try {
        const parsed = parseCodexOutput(stdout);
        resolve({
          content: parsed.content,
          tool_calls: parsed.tool_calls,
          events: parsed.events,
          raw: stdout,
        });
      } catch (error) {
        reject(error);
      }
    });

    const payload = prompt.endsWith('\n') ? prompt : `${prompt}\n`;
    proc.stdin.write(payload);
    proc.stdin.end();
  });
}

function parseCodexOutput(stdout) {
  const lines = stdout
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line.length > 0);
  const events = [];
  let content = '';
  const toolCalls = [];
  for (const line of lines) {
    let parsed;
    try {
      parsed = JSON.parse(line);
    } catch (error) {
      continue;
    }

    if (parsed.prompt) {
      continue;
    }

    if (parsed.msg) {
      const msg = parsed.msg;
      events.push(parsed);
      switch (msg.type) {
        case 'agent_message':
          if (typeof msg.message === 'string') {
            content = msg.message;
          }
          break;
        case 'task_complete':
          if (typeof msg.last_agent_message === 'string') {
            content = msg.last_agent_message;
          }
          break;
        case 'mcp_tool_call_begin':
        case 'mcp_tool_call_end':
          toolCalls.push(msg);
          break;
        default:
          break;
      }
    }
  }
  return { content, tool_calls: toolCalls, events };
}

async function executeSessionRun({ payload, messages, systemPrompt, sessionId, resumeSessionId }) {
  await sessionStore.ready;
  const promptPreview = extractPromptPreview(messages, systemPrompt);
  const runOptions = buildRunOptions({ ...payload, prompt_preview: promptPreview }, { prompt_preview: promptPreview });
  const beginResult = await sessionStore.beginRun({
    sessionId,
    metadata: {
      prompt_preview: promptPreview,
      timeout_ms: runOptions.timeoutMs,
      objective: runOptions.objective,
      model: runOptions.model,
      nudge_prompt: runOptions.nudge_prompt,
      nudge_interval_ms: runOptions.nudge_interval_ms,
      resume_codex_session_id: resumeSessionId,
    },
  });

  const resolvedSessionId = beginResult.sessionId;
  const runId = beginResult.runId;
  const runMeta = beginResult.meta;
  const prompt = buildPrompt(messages, systemPrompt);

  try {
    const result = await runCodex(prompt, runOptions.model, {
      timeoutMs: runOptions.timeoutMs,
      cwd: runOptions.cwd,
      env: runOptions.env,
      resumeSessionId,
      onStdout: (chunk) => sessionStore.appendStdout(resolvedSessionId, chunk),
      onStderr: (chunk) => sessionStore.appendStderr(resolvedSessionId, chunk),
    });
    const codexSessionId = extractCodexSessionId(result.events)
      || resumeSessionId
      || runMeta.codex_session_id
      || null;
    await sessionStore.finishRun(resolvedSessionId, runId, {
      status: 'completed',
      codexSessionId,
      content: result.content,
      events: result.events,
    });
    return {
      session_id: resolvedSessionId,
      codex_session_id: codexSessionId,
      content: result.content,
      tool_calls: result.tool_calls,
      events: result.events,
      status: 'completed',
    };
  } catch (error) {
    const status = error.message && error.message.includes('timed out') ? 'timeout' : 'error';
    await sessionStore.finishRun(resolvedSessionId, runId, {
      status,
      codexSessionId: resumeSessionId,
      error: error.message,
    });
    throw error;
  }
}

async function runPromptWithWorker({ payload, messages, systemPrompt, sessionId }) {
  await sessionStore.ready;
  const promptPreview = extractPromptPreview(messages, systemPrompt);
  const runOptions = buildRunOptions({ ...payload, prompt_preview: promptPreview }, { prompt_preview: promptPreview });
  const beginResult = await sessionStore.beginRun({
    sessionId,
    metadata: {
      prompt_preview: promptPreview,
      timeout_ms: runOptions.timeoutMs,
      objective: runOptions.objective,
      model: runOptions.model,
      nudge_prompt: runOptions.nudge_prompt,
      nudge_interval_ms: runOptions.nudge_interval_ms,
      idle_timeout_ms: runOptions.idle_timeout_ms,
    },
  });

  const resolvedSessionId = beginResult.sessionId;
  const meta = await sessionStore.getMeta(resolvedSessionId);
  const worker = await ensureSessionWorker(resolvedSessionId, {
    cwd: runOptions.cwd,
    env: runOptions.env || undefined,
    idleTimeoutMs: meta?.idle_timeout_ms || runOptions.idle_timeout_ms,
  });

  try {
    const result = await worker.sendPrompt({
      messages,
      systemPrompt,
      timeoutMs: runOptions.timeoutMs,
      promptPreview,
    });
    await sessionStore.finishRun(resolvedSessionId, beginResult.runId, {
      status: result.status,
      codexSessionId: result.codex_session_id,
      content: result.content,
      events: result.events,
    });
    return {
      gateway_session_id: resolvedSessionId,
      codex_session_id: result.codex_session_id,
      status: result.status,
      content: result.content,
      tool_calls: result.tool_calls,
      events: result.events,
    };
  } catch (error) {
    await sessionStore.finishRun(resolvedSessionId, beginResult.runId, {
      status: 'error',
      error: error.message,
    });
    throw error;
  }
}

async function handleCompletion(req, res) {
  let body = '';
  try {
    body = await readBody(req);
  } catch (error) {
    console.error('[codex-gateway] read error:', error.message);
    sendError(res, 413, error.message);
    return;
  }

  const parsed = safeJsonParse(body || '{}');
  if (!parsed.ok) {
    sendError(res, 400, 'Invalid JSON payload');
    return;
  }
  const payload = parsed.value;
  const messages = Array.isArray(payload.messages) ? payload.messages : [];
  const systemPrompt = typeof payload.system_prompt === 'string' ? payload.system_prompt : '';
  if (messages.length === 0) {
    sendError(res, 400, 'messages array is required');
    return;
  }

  await sessionStore.ready;

  const resumeTarget = typeof payload.session_id === 'string' ? payload.session_id.trim() : '';
  const resolvedSessionId = sessionStore.resolveSessionId(resumeTarget);
  const resumeSessionId = typeof payload.resume_session_id === 'string'
    ? payload.resume_session_id.trim()
    : null;
  const persistentFlag = typeof payload.persistent === 'boolean'
    ? payload.persistent
    : parseBoolean(payload.persistent);
  const parentMeta = resolvedSessionId ? await sessionStore.getMeta(resolvedSessionId) : null;
  const codexResumeId = resumeSessionId || (parentMeta && parentMeta.codex_session_id) || null;
  const useWorker = Boolean(persistentFlag) || Boolean(resolvedSessionId);

  try {
    if (useWorker) {
      const result = await runPromptWithWorker({
        payload,
        messages,
        systemPrompt,
        sessionId: resolvedSessionId,
      });
      sendJson(res, 200, {
        ...result,
        session_url: `/sessions/${result.codex_session_id || result.gateway_session_id}`,
      });
      return;
    }

    const result = await executeSessionRun({
      payload,
      messages,
      systemPrompt,
      sessionId: resolvedSessionId,
      resumeSessionId: codexResumeId,
    });
    sendJson(res, 200, {
      gateway_session_id: result.session_id,
      codex_session_id: result.codex_session_id,
      status: result.status,
      content: result.content,
      tool_calls: result.tool_calls,
      events: result.events,
      session_url: `/sessions/${result.codex_session_id || result.session_id}`,
    });
  } catch (error) {
    console.error('[codex-gateway] completion error:', error.message);
    sendError(res, 500, error.message || 'Codex execution failed');
  }
}

async function handleSessionList(req, res, url) {
  await sessionStore.ready;
  const limitRaw = url.searchParams.get('limit');
  const limit = limitRaw ? parseInt(limitRaw, 10) : null;
  const sessions = await sessionStore.listSessions(limit && !Number.isNaN(limit) ? limit : undefined);
  sendJson(res, 200, { sessions, count: sessions.length });
}

async function handleSessionDetail(req, res, sessionIdentifier, url) {
  await sessionStore.ready;
  const resolvedId = sessionStore.resolveSessionId(sessionIdentifier);
  if (!resolvedId) {
    sendError(res, 404, `Session '${sessionIdentifier}' not found`);
    return;
  }
  const tailLines = parseTailParam(url);
  const includeStderr = parseBoolean(url.searchParams.get('include_stderr'));
  const includeEvents = parseBoolean(url.searchParams.get('include_events'));
  const meta = await sessionStore.getMeta(resolvedId);
  if (!meta) {
    sendError(res, 404, 'Session metadata missing');
    return;
  }

  const [stdoutTail, stderrTail] = await Promise.all([
    sessionStore.readTail(resolvedId, 'stdout.log', tailLines),
    includeStderr ? sessionStore.readTail(resolvedId, 'stderr.log', tailLines) : Promise.resolve(''),
  ]);

  let events = [];
  if (includeEvents) {
    try {
      const data = await fsp.readFile(sessionStore.eventsPath(resolvedId), 'utf8');
      events = data.split(/\r?\n/).filter(Boolean).map((line) => JSON.parse(line));
    } catch (error) {
      if (error.code !== 'ENOENT') {
        console.error('[codex-gateway] failed to read events:', error.message);
      }
    }
  }

  sendJson(res, 200, {
    session_id: meta.session_id,
    codex_session_id: meta.codex_session_id,
    status: meta.status,
    created_at: meta.created_at,
    updated_at: meta.updated_at,
    last_activity_at: meta.last_activity_at,
    model: meta.model,
    objective: meta.objective,
    nudge_prompt: meta.nudge_prompt,
    nudge_interval_ms: meta.nudge_interval_ms,
    worker_state: meta.worker_state || 'stopped',
    worker_pid: Object.prototype.hasOwnProperty.call(meta, 'worker_pid') ? meta.worker_pid : null,
    execution_timeout_ms: meta.execution_timeout_ms || DEFAULT_TIMEOUT_MS,
    idle_timeout_ms: meta.idle_timeout_ms || DEFAULT_IDLE_TIMEOUT_MS,
    runs: meta.runs,
    stdout: {
      tail: stdoutTail,
      tail_lines: tailLines,
    },
    stderr: includeStderr ? { tail: stderrTail, tail_lines: tailLines } : undefined,
    events: includeEvents ? events : undefined,
  });
}

async function handleSessionSearch(req, res, sessionIdentifier, url) {
  await sessionStore.ready;
  const resolvedId = sessionStore.resolveSessionId(sessionIdentifier);
  if (!resolvedId) {
    sendError(res, 404, `Session '${sessionIdentifier}' not found`);
    return;
  }
  const query = url.searchParams.get('q');
  if (!query) {
    sendError(res, 400, 'Query parameter q is required');
    return;
  }
  const fuzzy = parseBoolean(url.searchParams.get('fuzzy'));
  const maxResultsRaw = url.searchParams.get('max_results');
  const maxResults = maxResultsRaw ? parseInt(maxResultsRaw, 10) : 5;
  const minScoreRaw = url.searchParams.get('min_score');
  const minScore = minScoreRaw ? parseFloat(minScoreRaw) : undefined;
  try {
    const matches = await sessionStore.searchSession(resolvedId, query, {
      fuzzy,
      maxResults: !Number.isNaN(maxResults) && maxResults > 0 ? maxResults : 5,
      minScore: typeof minScore === 'number' && !Number.isNaN(minScore) ? minScore : undefined,
    });
    const meta = await sessionStore.getMeta(resolvedId);
    sendJson(res, 200, {
      session_id: resolvedId,
      codex_session_id: meta ? meta.codex_session_id : null,
      query,
      signals: matches,
    });
  } catch (error) {
    console.error('[codex-gateway] search error:', error.message);
    sendError(res, 500, 'Failed to search session');
  }
}

async function handleSessionPrompt(req, res, sessionIdentifier) {
  await sessionStore.ready;
  const resolvedId = sessionStore.resolveSessionId(sessionIdentifier);
  if (!resolvedId) {
    sendError(res, 404, `Session '${sessionIdentifier}' not found`);
    return;
  }
  const body = await readBody(req).catch((error) => {
    console.error('[codex-gateway] prompt body error:', error.message);
    return null;
  });
  if (body === null) {
    sendError(res, 413, 'Payload too large');
    return;
  }
  const parsed = safeJsonParse(body || '{}');
  if (!parsed.ok) {
    sendError(res, 400, 'Invalid JSON payload');
    return;
  }
  const payload = parsed.value;
  let messages = [];
  const systemPrompt = typeof payload.system_prompt === 'string' ? payload.system_prompt : '';
  if (Array.isArray(payload.messages) && payload.messages.length > 0) {
    messages = payload.messages;
  } else if (typeof payload.prompt === 'string' && payload.prompt.trim().length > 0) {
    messages = [{ role: 'user', content: payload.prompt }];
  } else {
    sendError(res, 400, 'messages or prompt is required');
    return;
  }

  const meta = await sessionStore.getMeta(resolvedId);
  if (!meta) {
    sendError(res, 404, 'Session metadata missing');
    return;
  }

  try {
    const result = await runPromptWithWorker({
      payload,
      messages,
      systemPrompt,
      sessionId: resolvedId,
    });
    sendJson(res, 200, result);
  } catch (error) {
    console.error('[codex-gateway] prompt error:', error.message);
    sendError(res, 500, error.message || 'Codex execution failed');
  }
}

async function handleSessionNudge(req, res, sessionIdentifier) {
  await sessionStore.ready;
  const resolvedId = sessionStore.resolveSessionId(sessionIdentifier);
  if (!resolvedId) {
    sendError(res, 404, `Session '${sessionIdentifier}' not found`);
    return;
  }
  const meta = await sessionStore.getMeta(resolvedId);
  if (!meta) {
    sendError(res, 404, 'Session metadata missing');
    return;
  }
  const body = await readBody(req).catch(() => null);
  if (body === null) {
    sendError(res, 413, 'Payload too large');
    return;
  }
  const parsed = safeJsonParse(body || '{}');
  if (!parsed.ok) {
    sendError(res, 400, 'Invalid JSON payload');
    return;
  }
  const payload = parsed.value;
  const promptText = typeof payload.prompt === 'string' ? payload.prompt : meta.nudge_prompt;
  if (!promptText) {
    sendError(res, 400, 'No nudge prompt configured');
    return;
  }
  const messages = [{ role: 'user', content: promptText }];
  try {
    const result = await runPromptWithWorker({
      payload,
      messages,
      systemPrompt: payload.system_prompt || '',
      sessionId: resolvedId,
    });
    sendJson(res, 200, result);
  } catch (error) {
    console.error('[codex-gateway] nudge error:', error.message);
    sendError(res, 500, error.message || 'Codex execution failed');
  }
}

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, `http://${req.headers.host || 'localhost'}`);
  const normalizedPath = url.pathname.endsWith('/') && url.pathname.length > 1
    ? url.pathname.slice(0, -1)
    : url.pathname;
  const method = req.method.toUpperCase();

  try {
    if ((method === 'GET' || method === 'HEAD') && normalizedPath === '/health') {
      sendJson(res, 200, { status: 'ok' });
      return;
    }

    if ((method === 'GET' || method === 'HEAD') && (normalizedPath === '/' || normalizedPath === '')) {
      sendJson(res, 200, {
        status: 'codex-gateway',
        endpoints: {
          health: '/health',
          completion: { path: '/completion', method: 'POST' },
          sessions: {
            list: { path: '/sessions', method: 'GET' },
            detail: { path: '/sessions/:id', method: 'GET' },
            search: { path: '/sessions/:id/search', method: 'GET' },
            prompt: { path: '/sessions/:id/prompt', method: 'POST' },
            nudge: { path: '/sessions/:id/nudge', method: 'POST' },
          },
        },
      });
      return;
    }

    const segments = normalizedPath.split('/').filter(Boolean);
    if (segments.length === 0 && method === 'POST' && normalizedPath === '/completion') {
      await handleCompletion(req, res);
      return;
    }

    if (segments.length === 1 && segments[0] === 'completion' && method === 'POST') {
      await handleCompletion(req, res);
      return;
    }

    if (segments.length === 1 && segments[0] === 'sessions' && method === 'GET') {
      await handleSessionList(req, res, url);
      return;
    }

    if (segments.length >= 2 && segments[0] === 'sessions') {
      const sessionId = decodeURIComponent(segments[1]);
      if (segments.length === 2 && method === 'GET') {
        await handleSessionDetail(req, res, sessionId, url);
        return;
      }
      if (segments.length === 3 && segments[2] === 'search' && method === 'GET') {
        await handleSessionSearch(req, res, sessionId, url);
        return;
      }
      if (segments.length === 3 && segments[2] === 'prompt' && method === 'POST') {
        await handleSessionPrompt(req, res, sessionId);
        return;
      }
      if (segments.length === 3 && segments[2] === 'nudge' && method === 'POST') {
        await handleSessionNudge(req, res, sessionId);
        return;
      }
    }

    sendError(res, 404, 'Not Found');
  } catch (error) {
    console.error('[codex-gateway] unhandled error:', error);
    sendError(res, 500, 'Internal Server Error');
  }
});

server.listen(DEFAULT_PORT, DEFAULT_HOST, () => {
  console.log(`[codex-gateway] listening on http://${DEFAULT_HOST}:${DEFAULT_PORT}`);
});

const shutdown = () => {
  console.log('[codex-gateway] shutting down');
  server.close(() => {
    process.exit(0);
  });
};

process.on('SIGINT', shutdown);
process.on('SIGTERM', shutdown);
