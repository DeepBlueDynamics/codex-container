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
// Default model: use gpt-4o-mini for ChatGPT accounts, or empty string to use Codex default
// Note: 'o4-mini' is not a valid model name - use 'gpt-4o-mini' instead
const DEFAULT_MODEL = process.env.CODEX_GATEWAY_DEFAULT_MODEL || '';
const CODEX_JSON_FLAG = process.env.CODEX_GATEWAY_JSON_FLAG || '--experimental-json';
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
    // Check for thread_id in thread.started events
    if (entry.type === 'thread.started' && typeof entry.thread_id === 'string' && entry.thread_id.trim().length > 0) {
      console.log('[codex-gateway] extractCodexSessionId: found thread_id from thread.started:', entry.thread_id);
      return entry.thread_id.trim();
    }
    const msg = entry.msg;
    if (!msg) {
      continue;
    }
    if (typeof msg.session_id === 'string' && msg.session_id.trim().length > 0) {
      console.log('[codex-gateway] extractCodexSessionId: found session_id from msg:', msg.session_id);
      return msg.session_id.trim();
    }
    if (msg.session && typeof msg.session.id === 'string' && msg.session.id.trim().length > 0) {
      console.log('[codex-gateway] extractCodexSessionId: found session.id from msg.session:', msg.session.id);
      return msg.session.id.trim();
    }
  }
  console.log('[codex-gateway] extractCodexSessionId: no session ID found in', events.length, 'events');
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

const DEFAULT_TRIGGER_FILE = process.env.CODEX_GATEWAY_TRIGGER_FILE
  || path.join(process.cwd(), '.codex-monitor-triggers.json');
const DISABLE_TRIGGER_SCHEDULER = parseBoolean(process.env.CODEX_GATEWAY_DISABLE_TRIGGERS);
const TRIGGER_WATCH_DEBOUNCE_MS = parseInt(process.env.CODEX_GATEWAY_TRIGGER_DEBOUNCE_MS || '750', 10);
const MIN_TRIGGER_DELAY_MS = 250;
const CODEX_HOME_PATH = process.env.CODEX_GATEWAY_CODEX_HOME
  || process.env.CODEX_HOME
  || process.env.HOME
  || '/opt/codex-home';
const SESSION_TRIGGER_ROOT = path.join(CODEX_HOME_PATH, 'sessions');
const EXTRA_TRIGGER_FILES = (process.env.CODEX_GATEWAY_TRIGGER_FILES || '')
  .split(',')
  .map((entry) => entry.trim())
  .filter(Boolean)
  .map((entry) => path.resolve(entry));

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
    this.verboseEventLog = parseBoolean(process.env.CODEX_GATEWAY_LOG_EVENTS);
    this.verboseStreamLog = parseBoolean(process.env.CODEX_GATEWAY_VERBOSE_STREAM);
  }

  buildArgs(meta) {
    const args = ['exec', '--dangerously-bypass-approvals-and-sandbox'];
    if (CODEX_JSON_FLAG && CODEX_JSON_FLAG.trim().length > 0) {
      args.push(CODEX_JSON_FLAG.trim());
    }
    args.push('--color=never', '--skip-git-repo-check');
    if (meta && meta.model) {
      args.push('--model', meta.model);
    }
    if (Array.isArray(EXTRA_ARGS) && EXTRA_ARGS.length > 0) {
      args.push(...EXTRA_ARGS);
    }
    args.push('-');
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
    const args = this.buildArgs(meta || {});
    console.log('[codex-gateway] launching worker', JSON.stringify({
      session_id: this.sessionId,
      argv: ['codex', ...args],
      cwd: spawnOptions.cwd,
      env_keys: this.options.env ? Object.keys(this.options.env) : [],
      resume_codex_session_id: meta?.codex_session_id || null,
    }));
    this.starting = new Promise((resolve, reject) => {
      const child = spawn('codex', args, spawnOptions);
      this.proc = child;
      this.store.setWorkerState(this.sessionId, 'starting', { worker_pid: child.pid });
      child.stdout.on('data', (chunk) => {
        if (this.verboseStreamLog) {
          console.log(`[codex-gateway] stdout chunk ${chunk.length} size: ${chunk.length} bytes`);
          const preview = chunk.toString().slice(0, 200).replace(/\n/g, '\\n');
          console.log(`[codex-gateway] stdout content preview: "${preview}"`);
        }
        this.handleStdout(chunk);
      });
      child.stderr.on('data', (chunk) => {
        if (this.verboseStreamLog) {
          console.log(`[codex-gateway] stderr chunk ${chunk.length} size: ${chunk.length} bytes`);
          const preview = chunk.toString().slice(0, 200).replace(/\n/g, '\\n');
          console.log(`[codex-gateway] stderr content preview: "${preview}"`);
        }
        this.handleStderr(chunk);
      });
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
    if (this.verboseEventLog && parsed && parsed.type) {
      const summary = parsed.type === 'item.completed'
        ? `${parsed.type} (${parsed.item?.type || ''})`
        : parsed.type;
      console.log(`[codex-gateway] >>> CODEX EVENT: ${summary}`);
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
        this.proc.stdin.end();
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
    const args = ['exec'];
    if (CODEX_JSON_FLAG && CODEX_JSON_FLAG.trim().length > 0) {
      args.push(CODEX_JSON_FLAG.trim());
    }
    args.push('--color=never', '--skip-git-repo-check');
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

    console.log('[codex-gateway] spawning codex', JSON.stringify({
      argv: ['codex', ...args],
      cwd,
      timeout_ms: timeoutMs,
      prompt_length: prompt.length,
    }));

    const proc = spawn('codex', args, {
      cwd,
      env,
      stdio: ['pipe', 'pipe', 'pipe'],
    });

    let stdout = '';
    let stderr = '';
    let finished = false;
    let stdoutChunks = 0;
    let stderrChunks = 0;
    const startTime = Date.now();

    const timer = setTimeout(() => {
      if (!finished) {
        finished = true;
        const elapsed = Date.now() - startTime;
        console.error('[codex-gateway] Codex exec TIMEOUT after', elapsed, 'ms (limit:', timeoutMs, 'ms)');
        console.error('[codex-gateway] stdout chunks received:', stdoutChunks, 'total bytes:', stdout.length);
        console.error('[codex-gateway] stderr chunks received:', stderrChunks, 'total bytes:', stderr.length);
        if (stdout.length > 0) {
          console.error('[codex-gateway] stdout preview (last 500 chars):', stdout.slice(-500));
          // Try to extract thread_id even on timeout
          try {
            const lines = stdout.split('\n').filter(l => l.trim());
            for (const line of lines) {
              try {
                const parsed = JSON.parse(line);
                if (parsed.type === 'thread.started' && parsed.thread_id) {
                  console.error('[codex-gateway] TIMEOUT: Found thread_id in stdout:', parsed.thread_id);
                }
              } catch (e) {
                // Not JSON, skip
              }
            }
          } catch (e) {
            // Ignore parse errors
          }
        }
        if (stderr.length > 0) {
          console.error('[codex-gateway] stderr preview (last 500 chars):', stderr.slice(-500));
        }
        proc.kill('SIGTERM');
        reject(new Error(`Codex exec timed out after ${timeoutMs}ms`));
      }
    }, timeoutMs);

    proc.stdout.on('data', (chunk) => {
      const text = chunk.toString();
      stdout += text;
      stdoutChunks++;
      if (stdoutChunks <= 5 || stdoutChunks % 10 === 0) {
        console.log('[codex-gateway] stdout chunk', stdoutChunks, 'size:', chunk.length, 'bytes');
      }
      // Log first few chunks and every 10th chunk with content preview
      if (stdoutChunks <= 3 || stdoutChunks % 10 === 0) {
        const preview = text.length > 200 ? text.slice(0, 200) + '...' : text;
        console.log('[codex-gateway] stdout content preview:', JSON.stringify(preview));
      }
      // Try to parse JSON lines as they come in and log ALL events
      const lines = text.split('\n').filter(l => l.trim());
      for (const line of lines) {
        if (line.trim().startsWith('{')) {
          try {
            const parsed = JSON.parse(line);
            
            // Log all event types
            const eventType = parsed.type || parsed.msg?.type || 'unknown';
            console.log('[codex-gateway] >>> CODEX EVENT:', eventType);
            
            // Log thread/turn events
            if (parsed.type === 'thread.started' && parsed.thread_id) {
              console.log('[codex-gateway] >>> Thread started, ID:', parsed.thread_id);
            }
            if (parsed.type === 'turn.started') {
              console.log('[codex-gateway] >>> Turn started - AI is processing...');
            }
            if (parsed.type === 'turn.completed') {
              console.log('[codex-gateway] >>> Turn completed');
            }
            
            // Log agent messages (AI responses)
            if (parsed.msg?.type === 'agent_message' && parsed.msg.message) {
              const msg = parsed.msg.message;
              console.log('[codex-gateway] >>> AI MESSAGE (length:', msg.length, 'chars):');
              console.log('[codex-gateway] >>>', msg.slice(0, 500) + (msg.length > 500 ? '...' : ''));
            }
            
            // Log agent message deltas (streaming responses)
            if (parsed.msg?.type === 'agent_message_delta' && parsed.msg.delta) {
              console.log('[codex-gateway] >>> AI streaming:', JSON.stringify(parsed.msg.delta));
            }
            
            // Log agent reasoning
            if (parsed.msg?.type === 'agent_reasoning' && parsed.msg.text) {
              console.log('[codex-gateway] >>> AI REASONING:', parsed.msg.text.slice(0, 300));
            }
            
            // Log tool calls in detail
            if (parsed.msg?.type === 'mcp_tool_call_begin') {
              const toolName = parsed.msg.name || parsed.msg.tool_name || 'unknown';
              const toolArgs = parsed.msg.arguments || parsed.msg.args || {};
              const isGnosisCrawl = toolName === 'crawl_url' || toolName === 'crawl_batch' || toolName === 'raw_html';
              const prefix = isGnosisCrawl ? '[codex-gateway] 🔍 GNOSIS-CRAWL' : '[codex-gateway] >>> TOOL CALL BEGIN';
              console.log(prefix + ':', toolName);
              if (Object.keys(toolArgs).length > 0) {
                console.log('[codex-gateway] >>> Tool arguments:', JSON.stringify(toolArgs).slice(0, 300));
                if (isGnosisCrawl && toolArgs.url) {
                  console.log('[codex-gateway] 🔍 GNOSIS-CRAWL: Will POST to http://gnosis-crawl:8080/api/markdown (or /api/raw)');
                  console.log('[codex-gateway] 🔍 GNOSIS-CRAWL: Target URL:', toolArgs.url);
                }
              }
            }
            if (parsed.msg?.type === 'mcp_tool_call_end') {
              const toolName = parsed.msg.name || parsed.msg.tool_name || 'unknown';
              const result = parsed.msg.result || parsed.msg.content || '';
              const isGnosisCrawl = toolName === 'crawl_url' || toolName === 'crawl_batch' || toolName === 'raw_html';
              const prefix = isGnosisCrawl ? '[codex-gateway] 🔍 GNOSIS-CRAWL' : '[codex-gateway] >>> TOOL CALL END';
              console.log(prefix + ':', toolName);
              if (result) {
                const resultStr = typeof result === 'string' ? result : JSON.stringify(result);
                if (isGnosisCrawl) {
                  console.log('[codex-gateway] 🔍 GNOSIS-CRAWL: Result received (check gnosis-crawl logs for HTTP request details)');
                  console.log('[codex-gateway] 🔍 GNOSIS-CRAWL: Result preview:', resultStr.slice(0, 500));
                } else {
                  console.log('[codex-gateway] >>> Tool result preview:', resultStr.slice(0, 300));
                }
              }
            }
            
            // Log task completion
            if (parsed.msg?.type === 'task_complete') {
              console.log('[codex-gateway] >>> TASK COMPLETE');
              if (parsed.msg.last_agent_message) {
                console.log('[codex-gateway] >>> Final message:', parsed.msg.last_agent_message.slice(0, 300));
              }
            }
            
            // Log item completions (reasoning, messages, etc.)
            if (parsed.type === 'item.completed' && parsed.item) {
              const itemType = parsed.item.type || 'unknown';
              console.log('[codex-gateway] >>> Item completed:', itemType);
              
              // Enhanced logging for agent messages (AI responses)
              if (itemType === 'agent_message' && parsed.item) {
                const messageText = parsed.item.text || parsed.item.message || '';
                const messageId = parsed.item.id || 'unknown';
                
                console.log('[codex-gateway] 💬 AGENT MESSAGE COMPLETED:');
                console.log('[codex-gateway] 💬   Message ID:', messageId);
                console.log('[codex-gateway] 💬   Length:', messageText.length, 'chars');
                
                // Log full message, but format it nicely if it's long
                if (messageText.length > 0) {
                  if (messageText.length <= 1000) {
                    console.log('[codex-gateway] 💬   Full Message:');
                    console.log('[codex-gateway] 💬   ' + messageText.split('\n').join('\n[codex-gateway] 💬   '));
                  } else {
                    // For long messages, show first 1000 chars and last 500 chars
                    console.log('[codex-gateway] 💬   Message (first 1000 chars):');
                    console.log('[codex-gateway] 💬   ' + messageText.slice(0, 1000).split('\n').join('\n[codex-gateway] 💬   ') + '...');
                    console.log('[codex-gateway] 💬   ... (truncated, showing last 500 chars) ...');
                    console.log('[codex-gateway] 💬   ' + messageText.slice(-500).split('\n').join('\n[codex-gateway] 💬   '));
                    console.log('[codex-gateway] 💬   Total length:', messageText.length, 'chars');
                  }
                }
              }
              
              // Enhanced logging for reasoning items
              if (itemType === 'reasoning' && parsed.item.text) {
                const reasoningText = parsed.item.text;
                console.log('[codex-gateway] 🤔 REASONING:');
                if (reasoningText.length <= 500) {
                  console.log('[codex-gateway] 🤔   ' + reasoningText);
                } else {
                  console.log('[codex-gateway] 🤔   ' + reasoningText.slice(0, 500) + '...');
                  console.log('[codex-gateway] 🤔   (length:', reasoningText.length, 'chars)');
                }
              }
              
              // Enhanced logging for MCP tool calls
              if (itemType === 'mcp_tool_call' && parsed.item) {
                const server = parsed.item.server || 'unknown';
                const tool = parsed.item.tool || parsed.item.name || 'unknown';
                const status = parsed.item.status || 'unknown';
                const error = parsed.item.error;
                
                // Create emoji prefix based on server/tool
                let emoji = '🔧';
                let prefix = '[codex-gateway]';
                if (server === 'gnosis-crawl' || tool.includes('crawl')) {
                  emoji = '🔍';
                  prefix = '[codex-gateway] 🔍 GNOSIS-CRAWL';
                } else if (server === 'serpapi-search' || tool.includes('serp') || tool.includes('google_search')) {
                  emoji = '🔎';
                  prefix = '[codex-gateway] 🔎 SERPAPI';
                } else if (server === 'marketbot') {
                  emoji = '📊';
                  prefix = '[codex-gateway] 📊 MARKETBOT';
                } else {
                  prefix = `[codex-gateway] ${emoji} MCP TOOL`;
                }
                
                console.log(`${prefix} TOOL CALL COMPLETED:`);
                console.log(`${prefix}   Server: ${server}`);
                console.log(`${prefix}   Tool: ${tool}`);
                console.log(`${prefix}   Status: ${status}`);
                
                if (error) {
                  console.error(`${prefix}   ERROR:`, error);
                }
                
                // Log tool arguments if available
                if (parsed.item.arguments) {
                  const argsStr = JSON.stringify(parsed.item.arguments, null, 2);
                  if (argsStr.length <= 1000) {
                    console.log(`${prefix}   Arguments:`);
                    console.log(argsStr.split('\n').map(line => `${prefix}     ${line}`).join('\n'));
                  } else {
                    console.log(`${prefix}   Arguments (preview):`, argsStr.slice(0, 500) + '...');
                    console.log(`${prefix}   Arguments (full length):`, argsStr.length, 'chars');
                  }
                }
                
                // Log full result if available (with better formatting)
                if (parsed.item.result) {
                  let resultStr = '';
                  let resultObj = null;
                  
                  // Handle different result structures
                  if (typeof parsed.item.result === 'string') {
                    resultStr = parsed.item.result;
                  } else if (parsed.item.result.content && Array.isArray(parsed.item.result.content)) {
                    // MCP result format with content array
                    const contentItems = parsed.item.result.content;
                    resultStr = contentItems.map(item => {
                      if (item.type === 'text' && item.text) {
                        return item.text;
                      } else if (typeof item === 'string') {
                        return item;
                      } else {
                        return JSON.stringify(item);
                      }
                    }).join('\n');
                    resultObj = parsed.item.result;
                  } else {
                    resultStr = JSON.stringify(parsed.item.result, null, 2);
                    resultObj = parsed.item.result;
                  }
                  
                  console.log(`${prefix}   Result (length: ${resultStr.length} chars):`);
                  
                  // For large results, show structured preview
                  if (resultStr.length <= 2000) {
                    // Show full result for smaller responses
                    const lines = resultStr.split('\n');
                    if (lines.length <= 50) {
                      lines.forEach(line => {
                        console.log(`${prefix}     ${line}`);
                      });
                    } else {
                      // Show first 25 and last 25 lines
                      lines.slice(0, 25).forEach(line => {
                        console.log(`${prefix}     ${line}`);
                      });
                      console.log(`${prefix}     ... (${lines.length - 50} lines omitted) ...`);
                      lines.slice(-25).forEach(line => {
                        console.log(`${prefix}     ${line}`);
                      });
                    }
                  } else {
                    // For very large results, show preview
                    console.log(`${prefix}     ${resultStr.slice(0, 1000)}...`);
                    console.log(`${prefix}     ... (${resultStr.length - 1000} more chars) ...`);
                    console.log(`${prefix}     ${resultStr.slice(-500)}`);
                    
                    // If it's structured data, try to extract key info
                    if (resultObj && typeof resultObj === 'object') {
                      if (resultObj.success !== undefined) {
                        console.log(`${prefix}     Success: ${resultObj.success}`);
                      }
                      if (resultObj.data) {
                        console.log(`${prefix}     Has data object`);
                      }
                      if (resultObj.error) {
                        console.log(`${prefix}     Error: ${resultObj.error}`);
                      }
                    }
                  }
                }
              } else if (itemType === 'mcp_tool_call') {
                // Fallback if structure is different
                console.log('[codex-gateway] >>> MCP TOOL CALL completed (structure:', Object.keys(parsed.item).join(', '), ')');
              }
              
              // Log any text content from the item
              if (parsed.item.text && itemType !== 'agent_message' && itemType !== 'reasoning') {
                const textContent = parsed.item.text;
                if (textContent.length <= 500) {
                  console.log('[codex-gateway] >>> Item text:', textContent);
                } else {
                  console.log('[codex-gateway] >>> Item text (preview):', textContent.slice(0, 500) + '...');
                  console.log('[codex-gateway] >>> Item text (full length):', textContent.length, 'chars');
                }
              }
            }
            
            // Log item started events (especially for tool calls)
            if (parsed.type === 'item.started' && parsed.item) {
              const itemType = parsed.item.type || 'unknown';
              
              // Enhanced logging for MCP tool calls
              if (itemType === 'mcp_tool_call' && parsed.item) {
                const server = parsed.item.server || 'unknown';
                const tool = parsed.item.tool || parsed.item.name || 'unknown';
                
                // Create emoji prefix based on server/tool
                let emoji = '🔧';
                let prefix = '[codex-gateway]';
                if (server === 'gnosis-crawl' || tool.includes('crawl')) {
                  emoji = '🔍';
                  prefix = '[codex-gateway] 🔍 GNOSIS-CRAWL';
                } else if (server === 'serpapi-search' || tool.includes('serp') || tool.includes('google_search')) {
                  emoji = '🔎';
                  prefix = '[codex-gateway] 🔎 SERPAPI';
                } else if (server === 'marketbot') {
                  emoji = '📊';
                  prefix = '[codex-gateway] 📊 MARKETBOT';
                } else {
                  prefix = `[codex-gateway] ${emoji} MCP TOOL`;
                }
                
                console.log(`${prefix} TOOL CALL STARTED:`);
                console.log(`${prefix}   Server: ${server}`);
                console.log(`${prefix}   Tool: ${tool}`);
                
                // Log tool arguments if available
                if (parsed.item.arguments) {
                  const argsStr = JSON.stringify(parsed.item.arguments);
                  console.log(`${prefix}   Arguments:`, argsStr.slice(0, 300) + (argsStr.length > 300 ? '...' : ''));
                  
                  // Special handling for specific tools
                  if (tool === 'crawl_url' && parsed.item.arguments.url) {
                    console.log(`${prefix}   Target URL: ${parsed.item.arguments.url}`);
                  }
                  if ((tool === 'google_search' || tool === 'google_search_markdown') && parsed.item.arguments.query) {
                    console.log(`${prefix}   Search Query: ${parsed.item.arguments.query}`);
                  }
                }
              }
            }
            
            // Log any errors
            if (parsed.type === 'error' || parsed.msg?.type === 'error') {
              const errorMsg = parsed.message || parsed.msg?.message || parsed.error || 'Unknown error';
              console.error('[codex-gateway] >>> CODEX ERROR:', errorMsg);
            }
            
            // Log turn failures
            if (parsed.type === 'turn.failed') {
              console.error('[codex-gateway] >>> TURN FAILED');
              if (parsed.error) {
                console.error('[codex-gateway] >>> Error details:', JSON.stringify(parsed.error).slice(0, 300));
              }
            }
          } catch (e) {
            // Not JSON, ignore
          }
        }
      }
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
      stderrChunks++;
      console.log('[codex-gateway] stderr chunk', stderrChunks, 'size:', chunk.length, 'bytes, content:', text.slice(0, 200));
      if (typeof options.onStderr === 'function') {
        try {
          options.onStderr(text);
        } catch (error) {
          console.error('[codex-gateway] onStderr handler failed:', error.message);
        }
      }
    });

    proc.on('error', (error) => {
      console.error('[codex-gateway] codex spawn error:', error);
      if (!finished) {
        finished = true;
        clearTimeout(timer);
        reject(error);
      }
    });

    proc.on('close', (code) => {
      const elapsed = Date.now() - startTime;
      console.log('[codex-gateway] codex exited', code, 'after', elapsed, 'ms');
      console.log('[codex-gateway] total stdout chunks:', stdoutChunks, 'bytes:', stdout.length);
      console.log('[codex-gateway] total stderr chunks:', stderrChunks, 'bytes:', stderr.length);
      if (finished) {
        return;
      }
      finished = true;
      clearTimeout(timer);
      if (code !== 0) {
        const message = stderr || stdout || `Codex exited with code ${code}`;
        console.error('[codex-gateway] codex failed with code', code);
        if (stderr) {
          console.error('[codex-gateway] stderr output:', stderr.slice(0, 1000));
        }
        if (stdout) {
          console.error('[codex-gateway] stdout output (last 500 chars):', stdout.slice(-500));
        }
        reject(new Error(message.trim()));
        return;
      }
      try {
        console.log('[codex-gateway] parsing stdout, total length:', stdout.length);
        const parsed = parseCodexOutput(stdout);
        console.log('[codex-gateway] parsed output - content length:', parsed.content?.length || 0, 'events:', parsed.events?.length || 0, 'tool_calls:', parsed.tool_calls?.length || 0);
        if (parsed.content) {
          console.log('[codex-gateway] content preview:', parsed.content.slice(0, 200));
        }
        if (parsed.events && parsed.events.length > 0) {
          console.log('[codex-gateway] event types:', parsed.events.map(e => e.type || e.msg?.type).filter(Boolean).join(', '));
          // Extract and log thread_id from events
          const threadId = extractCodexSessionId(parsed.events);
          if (threadId) {
            console.log('[codex-gateway] extracted codex thread_id from events:', threadId);
          }
          
          // Extract MCP tool calls from events (item.completed with mcp_tool_call type)
          const mcpToolsCalled = [];
          for (const event of parsed.events) {
            if (event.type === 'item.completed' && event.item && event.item.type === 'mcp_tool_call') {
              const server = event.item.server || 'unknown';
              const tool = event.item.tool || event.item.name || 'unknown';
              const status = event.item.status || 'unknown';
              mcpToolsCalled.push({ server, tool, status });
            }
          }
          
          if (mcpToolsCalled.length > 0) {
            console.log('[codex-gateway] ========================================');
            console.log('[codex-gateway] 📋 MCP TOOLS CALLED SUMMARY:');
            mcpToolsCalled.forEach(({ server, tool, status }, idx) => {
              let emoji = '🔧';
              if (server === 'gnosis-crawl' || tool.includes('crawl')) emoji = '🔍';
              else if (server === 'serpapi-search' || tool.includes('serp') || tool.includes('google_search')) emoji = '🔎';
              else if (server === 'marketbot') emoji = '📊';
              console.log(`[codex-gateway]   ${idx + 1}. ${emoji} ${server}::${tool} (${status})`);
            });
            console.log('[codex-gateway] ========================================');
            const hasCrawlerCall = mcpToolsCalled.some(({ server, tool }) => (server === 'gnosis-crawl') || (tool && tool.includes('crawl')));
            const hasActivityMutation = mcpToolsCalled.some(
              ({ server, tool }) => server === 'marketbot' && typeof tool === 'string' && tool.includes('create_activity'),
            );
            if (!hasCrawlerCall) {
              console.warn('[codex-gateway] ⚠️  Run completed without any gnosis-crawl tool calls. Double-check prompts or tool availability.');
            }
            if (!hasActivityMutation) {
              console.warn('[codex-gateway] ⚠️  Run completed without any marketbot.create_activity calls. Ensure activities are being persisted when appropriate.');
            }
          } else {
            console.log('[codex-gateway] ⚠️  No MCP tool calls detected in events');
          }
        }
        if (parsed.tool_calls && parsed.tool_calls.length > 0) {
          console.log('[codex-gateway] tool calls (legacy format):', parsed.tool_calls.map(t => t.name || t.tool_name).filter(Boolean).join(', '));
        }
        const codexThreadId = extractCodexSessionId(parsed.events);
        resolve({
          content: parsed.content,
          tool_calls: parsed.tool_calls,
          events: parsed.events,
          raw: stdout,
          codex_thread_id: codexThreadId, // Add thread_id to result
        });
      } catch (error) {
        console.error('[codex-gateway] parseCodexOutput failed:', error.message);
        console.error('[codex-gateway] stdout that failed to parse (last 1000 chars):', stdout.slice(-1000));
        // Still try to return something useful
        const lines = stdout.split('\n').filter(l => l.trim());
        console.error('[codex-gateway] stdout line count:', lines.length);
        if (lines.length > 0) {
          console.error('[codex-gateway] first line:', lines[0].slice(0, 200));
          console.error('[codex-gateway] last line:', lines[lines.length - 1].slice(0, 200));
        }
        reject(error);
      }
    });

    proc.on('spawn', () => {
      console.log('[codex-gateway] codex process spawned, PID:', proc.pid);
    });

    const payload = prompt.endsWith('\n') ? prompt : `${prompt}\n`;
    console.log('[codex-gateway] sending prompt to codex, length:', payload.length, 'chars');
    proc.stdin.write(payload);
    proc.stdin.end();
    console.log('[codex-gateway] prompt sent, waiting for response...');
  });
}

function parseCodexOutput(stdout) {
  console.log('[codex-gateway] parseCodexOutput: input length', stdout.length);
  const lines = stdout
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line.length > 0);
  console.log('[codex-gateway] parseCodexOutput: found', lines.length, 'non-empty lines');
  const events = [];
  let content = '';
  const toolCalls = [];
  let parsedCount = 0;
  for (const line of lines) {
    let parsed;
    try {
      parsed = JSON.parse(line);
      parsedCount++;
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
            console.log('[codex-gateway] parseCodexOutput: found agent_message, length:', content.length);
            if (content.length <= 1000) {
              console.log('[codex-gateway] parseCodexOutput: 💬 Full agent message:');
              console.log('[codex-gateway] parseCodexOutput: ' + content.split('\n').join('\n[codex-gateway] parseCodexOutput: '));
            } else {
              console.log('[codex-gateway] parseCodexOutput: 💬 Agent message (first 1000 chars):');
              console.log('[codex-gateway] parseCodexOutput: ' + content.slice(0, 1000).split('\n').join('\n[codex-gateway] parseCodexOutput: ') + '...');
              console.log('[codex-gateway] parseCodexOutput: 💬 Agent message (last 500 chars):');
              console.log('[codex-gateway] parseCodexOutput: ' + content.slice(-500).split('\n').join('\n[codex-gateway] parseCodexOutput: '));
            }
          }
          break;
        case 'agent_message_delta':
          // Streaming message - accumulate if needed
          if (typeof msg.delta === 'string') {
            console.log('[codex-gateway] parseCodexOutput: agent_message_delta:', JSON.stringify(msg.delta));
          }
          break;
        case 'agent_reasoning':
          if (typeof msg.text === 'string') {
            console.log('[codex-gateway] parseCodexOutput: agent_reasoning:', msg.text.slice(0, 200));
          }
          break;
        case 'task_complete':
          if (typeof msg.last_agent_message === 'string') {
            content = msg.last_agent_message;
            console.log('[codex-gateway] parseCodexOutput: found task_complete, length:', content.length);
            console.log('[codex-gateway] parseCodexOutput: task_complete message:', content.slice(0, 300));
          }
          break;
        case 'mcp_tool_call_begin':
        case 'mcp_tool_call_end':
          toolCalls.push(msg);
          const toolName = msg.name || msg.tool_name || 'unknown';
          console.log('[codex-gateway] parseCodexOutput: found tool call', msg.type, toolName);
          if (msg.arguments || msg.args) {
            console.log('[codex-gateway] parseCodexOutput: tool arguments:', JSON.stringify(msg.arguments || msg.args).slice(0, 200));
          }
          if (msg.type === 'mcp_tool_call_end' && (msg.result || msg.content)) {
            const result = msg.result || msg.content;
            let resultStr = '';
            if (typeof result === 'string') {
              resultStr = result;
            } else if (result && result.content && Array.isArray(result.content)) {
              // MCP result format
              resultStr = result.content.map(item => {
                if (item.type === 'text' && item.text) return item.text;
                if (typeof item === 'string') return item;
                return JSON.stringify(item);
              }).join('\n');
            } else {
              resultStr = JSON.stringify(result, null, 2);
            }
            
            console.log('[codex-gateway] parseCodexOutput: 🔧 Tool result (length:', resultStr.length, 'chars):');
            if (resultStr.length <= 2000) {
              const lines = resultStr.split('\n');
              if (lines.length <= 30) {
                lines.forEach(line => {
                  console.log('[codex-gateway] parseCodexOutput:   ' + line);
                });
              } else {
                lines.slice(0, 15).forEach(line => {
                  console.log('[codex-gateway] parseCodexOutput:   ' + line);
                });
                console.log('[codex-gateway] parseCodexOutput:   ... (' + (lines.length - 30) + ' lines omitted) ...');
                lines.slice(-15).forEach(line => {
                  console.log('[codex-gateway] parseCodexOutput:   ' + line);
                });
              }
            } else {
              console.log('[codex-gateway] parseCodexOutput:   ' + resultStr.slice(0, 1000) + '...');
              console.log('[codex-gateway] parseCodexOutput:   ... (' + (resultStr.length - 1500) + ' chars omitted) ...');
              console.log('[codex-gateway] parseCodexOutput:   ' + resultStr.slice(-500));
            }
          }
          break;
        default:
          break;
      }
    } else if (parsed.type) {
      // Handle direct type events (not wrapped in msg)
      events.push(parsed);
      if (parsed.type === 'thread.started' && parsed.thread_id) {
        console.log('[codex-gateway] parseCodexOutput: found thread.started with thread_id:', parsed.thread_id);
      }
      if (parsed.type === 'turn.completed' && parsed.content) {
        content = parsed.content;
        console.log('[codex-gateway] parseCodexOutput: found turn.completed with content, length:', content.length);
      }
      // Extract MCP tool calls from item.completed events
      if (parsed.type === 'item.completed' && parsed.item && parsed.item.type === 'mcp_tool_call') {
        const server = parsed.item.server || 'unknown';
        const tool = parsed.item.tool || parsed.item.name || 'unknown';
        const status = parsed.item.status || 'unknown';
        // Add to toolCalls array for consistency
        toolCalls.push({
          type: 'mcp_tool_call',
          server,
          tool,
          name: tool,
          status,
          arguments: parsed.item.arguments,
          result: parsed.item.result,
          error: parsed.item.error,
        });
        console.log('[codex-gateway] parseCodexOutput: found MCP tool call in item.completed:', server, '::', tool, 'status:', status);
      }
    }
  }
  
  // Log summary of all MCP tools found
  const mcpTools = toolCalls.filter(t => t.server || t.type === 'mcp_tool_call');
  if (mcpTools.length > 0) {
    console.log('[codex-gateway] parseCodexOutput: MCP tools extracted:', mcpTools.map(t => `${t.server || 'unknown'}::${t.tool || t.name || 'unknown'}`).join(', '));
  }
  
  console.log('[codex-gateway] parseCodexOutput: parsed', parsedCount, 'JSON lines, found', events.length, 'events,', toolCalls.length, 'tool calls, content length:', content.length);
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
    const codexSessionId = result.codex_thread_id
      || extractCodexSessionId(result.events)
      || resumeSessionId
      || runMeta.codex_session_id
      || null;
    console.log('[codex-gateway] executeSessionRun: extracted codex_session_id:', codexSessionId, 'for gateway session:', resolvedSessionId);
    if (codexSessionId) {
      console.log('[codex-gateway] executeSessionRun: Session lookup - Gateway ID:', resolvedSessionId, 'Codex Thread ID:', codexSessionId);
      console.log('[codex-gateway] executeSessionRun: You can access this session using EITHER ID:');
      console.log('[codex-gateway] executeSessionRun:   curl http://localhost:4000/sessions/' + resolvedSessionId);
      console.log('[codex-gateway] executeSessionRun:   curl http://localhost:4000/sessions/' + codexSessionId);
    }
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
    // Even on timeout/error, try to extract thread_id from any stdout we captured
    let extractedThreadId = resumeSessionId || runMeta.codex_session_id || null;
    if (error.message && error.message.includes('timed out')) {
      // On timeout, try to read from stdout.log to extract thread_id
      try {
        const stdoutPath = sessionStore.stdoutPath(resolvedSessionId);
        const stdoutContent = await fsp.readFile(stdoutPath, 'utf8').catch(() => '');
        if (stdoutContent) {
          const lines = stdoutContent.split('\n').filter(l => l.trim());
          for (const line of lines) {
            try {
              const parsed = JSON.parse(line);
              if (parsed.type === 'thread.started' && parsed.thread_id) {
                extractedThreadId = parsed.thread_id;
                console.log('[codex-gateway] executeSessionRun: extracted thread_id from stdout.log on timeout:', extractedThreadId);
                break;
              }
            } catch (e) {
              // Not JSON, skip
            }
          }
        }
      } catch (e) {
        console.log('[codex-gateway] executeSessionRun: could not read stdout.log for thread_id extraction');
      }
    }
    console.log('[codex-gateway] executeSessionRun: error/timeout - Gateway ID:', resolvedSessionId, 'Codex Thread ID:', extractedThreadId || 'None');
    if (extractedThreadId) {
      console.log('[codex-gateway] executeSessionRun: You can access this session using EITHER ID:');
      console.log('[codex-gateway] executeSessionRun:   curl http://localhost:4000/sessions/' + resolvedSessionId);
      console.log('[codex-gateway] executeSessionRun:   curl http://localhost:4000/sessions/' + extractedThreadId);
    }
    await sessionStore.finishRun(resolvedSessionId, runId, {
      status,
      codexSessionId: extractedThreadId,
      error: error.message,
    });
    throw error;
  }
}

async function runPromptWithWorker({ payload, messages, systemPrompt, sessionId }) {
  await sessionStore.ready;
  const promptPreview = extractPromptPreview(messages, systemPrompt);
  const runOptions = buildRunOptions({ ...payload, prompt_preview: promptPreview }, { prompt_preview: promptPreview });

  const resolvedSessionId = sessionId ? sessionStore.resolveSessionId(sessionId) : null;
  const existingMeta = resolvedSessionId ? await sessionStore.getMeta(resolvedSessionId) : null;
  const resumeCodexSessionId = existingMeta?.codex_session_id || null;

  const result = await executeSessionRun({
    payload: { ...payload, prompt_preview: promptPreview },
    messages,
    systemPrompt,
    sessionId: resolvedSessionId || undefined,
    resumeSessionId: resumeCodexSessionId,
  });

  return {
    gateway_session_id: result.session_id,
    codex_session_id: result.codex_session_id,
    status: result.status,
    content: result.content,
    tool_calls: result.tool_calls,
    events: result.events,
  };
}

function parseIsoDate(value, contextLabel) {
  if (!value) {
    throw new Error(`${contextLabel || 'timestamp'} missing`);
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    throw new Error(`Invalid ISO timestamp '${value}'`);
  }
  return parsed;
}

function parseHhMm(value, contextLabel) {
  if (typeof value !== 'string' || value.trim().length === 0) {
    throw new Error(`${contextLabel || 'time'} missing`);
  }
  const match = value.trim().match(/^(\d{1,2}):(\d{2})$/);
  if (!match) {
    throw new Error(`Invalid time '${value}' (expected HH:MM)`);
  }
  const hour = parseInt(match[1], 10);
  const minute = parseInt(match[2], 10);
  if (hour < 0 || hour > 23 || minute < 0 || minute > 59) {
    throw new Error(`Time '${value}' outside 24h range`);
  }
  return { hour, minute };
}

const TIMEZONE_FORMATTERS = new Map();

function getTimeZoneFormatter(tzName) {
  const key = tzName || 'UTC';
  if (TIMEZONE_FORMATTERS.has(key)) {
    return TIMEZONE_FORMATTERS.get(key);
  }
  let formatter;
  try {
    formatter = new Intl.DateTimeFormat('en-US', {
      timeZone: key,
      calendar: 'iso8601',
      numberingSystem: 'latn',
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hourCycle: 'h23',
    });
  } catch (error) {
    formatter = new Intl.DateTimeFormat('en-US', {
      timeZone: 'UTC',
      calendar: 'iso8601',
      numberingSystem: 'latn',
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hourCycle: 'h23',
    });
  }
  TIMEZONE_FORMATTERS.set(key, formatter);
  return formatter;
}

function getTimeZoneParts(date, tzName) {
  const formatter = getTimeZoneFormatter(tzName);
  const parts = formatter.formatToParts(date);
  const result = {};
  for (const part of parts) {
    if (part.type === 'literal') {
      continue;
    }
    result[part.type] = parseInt(part.value, 10);
  }
  return result;
}

function getTimeZoneOffsetMs(tzName, date) {
  try {
    const parts = getTimeZoneParts(date, tzName);
    const asUtc = Date.UTC(
      parts.year,
      (parts.month || 1) - 1,
      parts.day || 1,
      parts.hour || 0,
      parts.minute || 0,
      parts.second || 0,
    );
    return asUtc - date.getTime();
  } catch (error) {
    return 0;
  }
}

function convertLocalPartsToUtc(tzName, parts) {
  const guess = Date.UTC(
    parts.year,
    (parts.month || 1) - 1,
    parts.day || 1,
    parts.hour || 0,
    parts.minute || 0,
    parts.second || 0,
  );
  let actual = guess;
  for (let i = 0; i < 3; i += 1) {
    const offset = getTimeZoneOffsetMs(tzName, new Date(actual));
    const candidate = guess - offset;
    if (Math.abs(candidate - actual) < 500) {
      actual = candidate;
      break;
    }
    actual = candidate;
  }
  return new Date(actual);
}

function buildDailyCandidate(tzName, hour, minute, reference) {
  const parts = getTimeZoneParts(reference, tzName);
  return convertLocalPartsToUtc(tzName, {
    year: parts.year,
    month: parts.month,
    day: parts.day,
    hour,
    minute,
    second: 0,
  });
}

function computeNextTriggerFire(record, referenceDate) {
  if (!record.enabled) {
    return null;
  }
  const schedule = record.schedule || {};
  const modeRaw = typeof schedule.mode === 'string' ? schedule.mode.toLowerCase() : null;
  const inferredMode = modeRaw
    || (schedule.interval_minutes || schedule.minutes ? 'interval'
      : schedule.time ? 'daily'
        : 'once');
  const now = referenceDate || new Date();

  if (inferredMode === 'once') {
    const targetIso = schedule.at || schedule.time || record.created_at;
    const target = parseIsoDate(targetIso, 'schedule.at');
    if (target <= now) {
      return null;
    }
    return target;
  }

  if (inferredMode === 'daily') {
    const tzName = schedule.timezone || schedule.tz || 'UTC';
    const { hour, minute } = parseHhMm(schedule.time || schedule.at || '00:00', 'schedule.time');
    let candidate = buildDailyCandidate(tzName, hour, minute, now);
    if (candidate <= now) {
      const future = new Date(now.getTime() + 25 * 60 * 60 * 1000);
      candidate = buildDailyCandidate(tzName, hour, minute, future);
    }
    return candidate;
  }

  if (inferredMode === 'interval') {
    const minutes = parseFloat(schedule.interval_minutes || schedule.minutes);
    if (!minutes || minutes <= 0) {
      throw new Error(`Trigger ${record.id} interval must be greater than zero`);
    }
    const stepMs = minutes * 60 * 1000;
    let base = record.last_fired ? parseIsoDate(record.last_fired, 'last_fired') : parseIsoDate(record.created_at, 'created_at');
    let candidate = new Date(base.getTime() + stepMs);
    const ceiling = now.getTime() + stepMs * 1000; // guard runaway loops
    while (candidate <= now && candidate.getTime() < ceiling) {
      base = candidate;
      candidate = new Date(candidate.getTime() + stepMs);
    }
    if (candidate <= now) {
      candidate = new Date(now.getTime() + stepMs);
    }
    return candidate;
  }

  throw new Error(`Unknown trigger schedule mode '${JSON.stringify(schedule.mode || schedule)}'`);
}

async function discoverSessionTriggerFiles() {
  const files = [];
  try {
    const entries = await fsp.readdir(SESSION_TRIGGER_ROOT, { withFileTypes: true });
    for (const entry of entries) {
      if (!entry.isDirectory()) {
        continue;
      }
      const triggerPath = path.join(SESSION_TRIGGER_ROOT, entry.name, 'triggers.json');
      files.push(triggerPath);
    }
  } catch (error) {
    if (error.code !== 'ENOENT') {
      console.error('[codex-gateway] failed to enumerate session triggers:', error.message);
    }
  }
  return files;
}

function dedupeTriggerFiles(files) {
  const result = [];
  const seen = new Set();
  for (const candidate of files) {
    const resolved = path.resolve(candidate);
    if (seen.has(resolved)) {
      continue;
    }
    seen.add(resolved);
    result.push(resolved);
  }
  return result;
}

class TriggerScheduler extends EventEmitter {
  constructor(options = {}) {
    super();
    this.triggerFile = path.resolve(options.triggerFile || DEFAULT_TRIGGER_FILE);
    this.dispatchPrompt = options.dispatchPrompt;
    this.jobs = new Map();
    this.triggers = new Map();
    this.started = false;
    this.debounceTimer = null;
    this.watcher = null;
  }

  async start() {
    if (this.started) {
      return;
    }
    this.started = true;
    await this.reload();
    this.startWatcher();
    console.log(`[codex-gateway] trigger scheduler watching ${this.triggerFile}`);
  }

  stop() {
    this.started = false;
    if (this.watcher) {
      this.watcher.close();
      this.watcher = null;
    }
    if (this.debounceTimer) {
      clearTimeout(this.debounceTimer);
      this.debounceTimer = null;
    }
    this.clearAllJobs();
  }

  async reload() {
    if (!this.started) {
      return;
    }
    let config;
    try {
      const raw = await fsp.readFile(this.triggerFile, 'utf8');
      config = JSON.parse(raw);
    } catch (error) {
      if (error.code === 'ENOENT') {
        this.clearAllJobs();
        this.triggers.clear();
        return;
      }
      console.error('[codex-gateway] trigger config parse error:', error.message);
      return;
    }
    const entries = Array.isArray(config.triggers) ? config.triggers : [];
    const seen = new Set();
    console.log(`[codex-gateway] reloading ${entries.length} trigger(s) from ${this.triggerFile}`);
    for (const entry of entries) {
      try {
        const normalized = this.normalize(entry);
        seen.add(normalized.id);
        this.schedule(normalized);
      } catch (error) {
        console.error('[codex-gateway] skipping trigger:', error.message);
      }
    }
    for (const key of Array.from(this.jobs.keys())) {
      if (!seen.has(key)) {
        this.cancel(key);
      }
    }
  }

  normalize(entry) {
    const id = String(entry.id || entry.trigger_id || crypto.randomUUID());
    const promptText = typeof entry.prompt_text === 'string' && entry.prompt_text.trim().length > 0
      ? entry.prompt_text
      : typeof entry.prompt === 'string'
        ? entry.prompt
        : '';
    if (promptText.trim().length === 0) {
      throw new Error(`Trigger ${id} missing prompt_text`);
    }
    const schedule = entry.schedule && typeof entry.schedule === 'object'
      ? entry.schedule
      : {};
    const normalized = {
      id,
      title: typeof entry.title === 'string' && entry.title.trim().length > 0 ? entry.title.trim() : id,
      description: typeof entry.description === 'string' ? entry.description : '',
      schedule,
      prompt_text: promptText,
      created_at: entry.created_at || new Date().toISOString(),
      enabled: entry.enabled !== false,
      tags: Array.isArray(entry.tags) ? entry.tags : [],
      last_fired: entry.last_fired || null,
      gateway_session_id: entry.gateway_session_id || null,
      system_prompt: typeof entry.system_prompt === 'string' ? entry.system_prompt : '',
      env: entry.env && typeof entry.env === 'object' ? entry.env : null,
      cwd: typeof entry.cwd === 'string' && entry.cwd.trim().length > 0 ? entry.cwd.trim() : null,
      timeout_ms: entry.timeout_ms || entry.max_duration_ms || null,
      idle_timeout_ms: entry.idle_timeout_ms || null,
    };
    this.triggers.set(id, normalized);
    return normalized;
  }

  schedule(record) {
    this.cancel(record.id);
    let nextFire = null;
    try {
      nextFire = computeNextTriggerFire(record, new Date());
    } catch (error) {
      console.error(`[codex-gateway] trigger ${record.id} scheduling error:`, error.message);
    }
    record.next_fire = nextFire ? nextFire.toISOString() : null;
    this.triggers.set(record.id, record);
    if (!nextFire) {
      return;
    }
    console.log(`[codex-gateway] trigger '${record.title}' scheduled for ${nextFire.toISOString()} (${this.triggerFile})`);
    const delay = Math.max(nextFire.getTime() - Date.now(), MIN_TRIGGER_DELAY_MS);
    const timer = setTimeout(() => {
      this.execute(record.id).catch((error) => {
        console.error(`[codex-gateway] trigger ${record.id} execution error:`, error.message);
      });
    }, delay);
    this.jobs.set(record.id, timer);
  }

  cancel(triggerId) {
    const timer = this.jobs.get(triggerId);
    if (timer) {
      clearTimeout(timer);
      this.jobs.delete(triggerId);
    }
  }

  clearAllJobs() {
    for (const timer of this.jobs.values()) {
      clearTimeout(timer);
    }
    this.jobs.clear();
  }

  async execute(triggerId) {
    this.cancel(triggerId);
    const record = this.triggers.get(triggerId);
    if (!record) {
      return;
    }
    const nowIso = new Date().toISOString();
    const promptPayload = {
      payload: {
        timeout_ms: record.timeout_ms || undefined,
        idle_timeout_ms: record.idle_timeout_ms || undefined,
        env: record.env || undefined,
        cwd: record.cwd || undefined,
        persistent: true,
      },
      messages: [{ role: 'user', content: record.prompt_text }],
      systemPrompt: record.system_prompt || '',
      sessionId: record.gateway_session_id || undefined,
      triggerId,
      triggerTitle: record.title,
    };
    console.log('[codex-gateway] trigger dispatch', JSON.stringify({
      trigger_id: triggerId,
      title: record.title,
      payload: {
        timeout_ms: promptPayload.payload.timeout_ms || DEFAULT_TIMEOUT_MS,
        idle_timeout_ms: promptPayload.payload.idle_timeout_ms || DEFAULT_IDLE_TIMEOUT_MS,
        env_keys: promptPayload.payload.env ? Object.keys(promptPayload.payload.env) : [],
        cwd: promptPayload.payload.cwd,
        persistent: promptPayload.payload.persistent,
        session_id: promptPayload.sessionId || null,
      },
    }));
    let runSucceeded = false;
    try {
      const result = await this.dispatchPrompt(promptPayload);
      runSucceeded = Boolean(result && result.status !== 'error');
      const gatewaySessionId = result && result.gateway_session_id
        ? result.gateway_session_id
        : record.gateway_session_id;
      await this.updateTriggerRecord(record.id, {
        last_fired: nowIso,
        gateway_session_id: gatewaySessionId || null,
      });
      record.last_fired = nowIso;
      record.gateway_session_id = gatewaySessionId || null;
    } catch (error) {
      console.error(`[codex-gateway] trigger ${record.id} run failed:`, error.message);
    } finally {
      if (runSucceeded && this.isOneShot(record)) {
        console.log(`[codex-gateway] removing completed one-shot trigger ${record.id}`);
        await this.removeTriggerRecord(record.id);
        this.triggers.delete(record.id);
        this.jobs.delete(record.id);
      } else {
        this.schedule(record);
      }
    }
  }

  async updateTriggerRecord(triggerId, patch) {
    try {
      const raw = await fsp.readFile(this.triggerFile, 'utf8');
      const config = JSON.parse(raw);
      const triggers = Array.isArray(config.triggers) ? config.triggers : [];
      let changed = false;
      const updated = triggers.map((entry) => {
        const entryId = String(entry.id || entry.trigger_id || '');
        if (entryId === triggerId) {
          changed = true;
          return { ...entry, ...patch };
        }
        return entry;
      });
      if (changed) {
        config.triggers = updated;
        config.updated_at = new Date().toISOString();
        await fsp.writeFile(this.triggerFile, `${JSON.stringify(config, null, 2)}\n`, 'utf8');
      }
    } catch (error) {
      if (error.code !== 'ENOENT') {
        console.error('[codex-gateway] failed to persist trigger metadata:', error.message);
      }
    }
  }

  async removeTriggerRecord(triggerId) {
    try {
      const raw = await fsp.readFile(this.triggerFile, 'utf8');
      const config = JSON.parse(raw);
      const triggers = Array.isArray(config.triggers) ? config.triggers : [];
      const filtered = triggers.filter((entry) => String(entry.id || entry.trigger_id || '') !== triggerId);
      if (filtered.length === triggers.length) {
        return;
      }
      config.triggers = filtered;
      config.updated_at = new Date().toISOString();
      await fsp.writeFile(this.triggerFile, `${JSON.stringify(config, null, 2)}\n`, 'utf8');
    } catch (error) {
      if (error.code !== 'ENOENT') {
        console.error('[codex-gateway] failed to remove trigger:', error.message);
      }
    }
  }

  isOneShot(record) {
    const mode = record?.schedule?.mode;
    return typeof mode === 'string' && mode.toLowerCase() === 'once';
  }

  startWatcher() {
    const directory = path.dirname(this.triggerFile);
    try {
      this.watcher = fs.watch(directory, (eventType, filename) => {
        if (!filename) {
          return;
        }
        if (path.basename(filename.toString()) !== path.basename(this.triggerFile)) {
          return;
        }
        if (eventType !== 'change' && eventType !== 'rename') {
          return;
        }
        console.log(`[codex-gateway] detected change in ${this.triggerFile} (${eventType})`);
        this.scheduleReload();
      });
    } catch (error) {
      console.error('[codex-gateway] unable to watch trigger file:', error.message);
    }
  }

  scheduleReload() {
    if (this.debounceTimer) {
      return;
    }
    this.debounceTimer = setTimeout(() => {
      this.debounceTimer = null;
      this.reload().catch((error) => {
        console.error('[codex-gateway] trigger reload failure:', error.message);
      });
    }, Math.max(TRIGGER_WATCH_DEBOUNCE_MS, 250));
  }
}

class TriggerSchedulerManager {
  constructor(options = {}) {
    this.dispatchPrompt = options.dispatchPrompt;
    this.defaultFile = options.defaultFile ? path.resolve(options.defaultFile) : null;
    this.extraFiles = Array.isArray(options.extraFiles) ? options.extraFiles.map((file) => path.resolve(file)) : [];
    this.includeSessionTriggers = options.includeSessionTriggers !== false;
    this.schedulers = new Map();
    this.refreshTimer = null;
    this.sessionWatcher = null;
  }

  async start() {
    await this.refreshSchedulers();
    this.startSessionWatcher();
  }

  stop() {
    if (this.sessionWatcher) {
      this.sessionWatcher.close();
      this.sessionWatcher = null;
    }
    if (this.refreshTimer) {
      clearTimeout(this.refreshTimer);
      this.refreshTimer = null;
    }
    for (const scheduler of this.schedulers.values()) {
      scheduler.stop();
    }
    this.schedulers.clear();
  }

  async refreshSchedulers() {
    const files = [];
    if (this.defaultFile) {
      files.push(this.defaultFile);
    }
    files.push(...this.extraFiles);
    if (this.includeSessionTriggers) {
      const discovered = await discoverSessionTriggerFiles();
      files.push(...discovered);
    }
    const uniqueFiles = dedupeTriggerFiles(files);
    const keep = new Set(uniqueFiles);
    for (const filePath of uniqueFiles) {
      await this.ensureScheduler(filePath);
    }
    for (const [filePath, scheduler] of Array.from(this.schedulers.entries())) {
      if (!keep.has(filePath)) {
        scheduler.stop();
        this.schedulers.delete(filePath);
      }
    }
  }

  async ensureScheduler(filePath) {
    if (this.schedulers.has(filePath)) {
      return;
    }
    const scheduler = new TriggerScheduler({
      triggerFile: filePath,
      dispatchPrompt: this.dispatchPrompt,
    });
    this.schedulers.set(filePath, scheduler);
    try {
      await scheduler.start();
      console.log(`[codex-gateway] trigger scheduler watching ${filePath}`);
    } catch (error) {
      console.error(`[codex-gateway] failed to start scheduler for ${filePath}:`, error.message);
    }
  }

  startSessionWatcher() {
    if (!this.includeSessionTriggers) {
      return;
    }
    try {
      this.sessionWatcher = fs.watch(SESSION_TRIGGER_ROOT, () => {
        this.scheduleRefresh();
      });
    } catch (error) {
      if (error.code !== 'ENOENT') {
        console.error('[codex-gateway] unable to watch session triggers:', error.message);
      }
    }
  }

  scheduleRefresh() {
    if (this.refreshTimer) {
      return;
    }
    this.refreshTimer = setTimeout(() => {
      this.refreshTimer = null;
      this.refreshSchedulers().catch((error) => {
        console.error('[codex-gateway] trigger refresh failure:', error.message);
      });
    }, Math.max(TRIGGER_WATCH_DEBOUNCE_MS, 250));
  }
}

async function handleCompletion(req, res) {
  const requestId = Math.random().toString(36).substring(7);
  console.log('[codex-gateway] completion request', requestId, 'started');
  let body = '';
  try {
    body = await readBody(req);
    console.log('[codex-gateway] request', requestId, 'body size:', body.length, 'bytes');
  } catch (error) {
    console.error('[codex-gateway] request', requestId, 'read error:', error.message);
    sendError(res, 413, error.message);
    return;
  }

  const parsed = safeJsonParse(body || '{}');
  if (!parsed.ok) {
    console.error('[codex-gateway] request', requestId, 'invalid JSON');
    sendError(res, 400, 'Invalid JSON payload');
    return;
  }
  const payload = parsed.value;
  const messages = Array.isArray(payload.messages) ? payload.messages : [];
  const systemPrompt = typeof payload.system_prompt === 'string' ? payload.system_prompt : '';
  if (messages.length === 0) {
    console.error('[codex-gateway] request', requestId, 'no messages');
    sendError(res, 400, 'messages array is required');
    return;
  }
  console.log('[codex-gateway] request', requestId, 'messages:', messages.length, 'timeout_ms:', payload.timeout_ms || 'default');
  if (messages.length > 0 && messages[0].content) {
    console.log('[codex-gateway] request', requestId, 'first message preview:', messages[0].content.slice(0, 100));
  }

  try {
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

    console.log('[codex-gateway] request', requestId, 'executing, useWorker:', useWorker);
    if (useWorker) {
      const result = await runPromptWithWorker({
        payload,
        messages,
        systemPrompt,
        sessionId: resolvedSessionId,
      });
      console.log('[codex-gateway] request', requestId, 'worker result - status:', result.status, 'content length:', result.content?.length || 0);
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
    console.log('[codex-gateway] request', requestId, 'session run result - status:', result.status, 'content length:', result.content?.length || 0, 'events:', result.events?.length || 0);
    console.log('[codex-gateway] request', requestId, 'session IDs - gateway:', result.session_id, 'codex:', result.codex_session_id);
    if (result.content) {
      console.log('[codex-gateway] request', requestId, 'content preview:', result.content.slice(0, 200));
    }
    // Log both session IDs for easy lookup
    console.log('[codex-gateway] request', requestId, 'SESSION INFO - Use either ID to access:');
    console.log('[codex-gateway] request', requestId, '  Gateway Session ID:', result.session_id);
    console.log('[codex-gateway] request', requestId, '  Codex Thread ID:', result.codex_session_id);
    console.log('[codex-gateway] request', requestId, '  Access via: curl http://localhost:4000/sessions/' + (result.codex_session_id || result.session_id));
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
    console.error('[codex-gateway] request', requestId, 'completion error:', error.message);
    console.error('[codex-gateway] request', requestId, 'error stack:', error.stack);
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

let triggerSchedulerManager = null;
if (!DISABLE_TRIGGER_SCHEDULER) {
  triggerSchedulerManager = new TriggerSchedulerManager({
    defaultFile: DEFAULT_TRIGGER_FILE,
    extraFiles: EXTRA_TRIGGER_FILES,
    includeSessionTriggers: true,
    dispatchPrompt: async (options) => runPromptWithWorker(options),
  });
  triggerSchedulerManager.start().catch((error) => {
    console.error('[codex-gateway] failed to start trigger schedulers:', error.message);
  });
} else {
  console.log('[codex-gateway] trigger scheduler disabled by configuration');
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
  if (triggerSchedulerManager) {
    triggerSchedulerManager.stop();
  }
  server.close(() => {
    process.exit(0);
  });
};

process.on('SIGINT', shutdown);
process.on('SIGTERM', shutdown);
