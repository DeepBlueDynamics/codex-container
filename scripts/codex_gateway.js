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
const CODEX_JSON_FLAG = process.env.CODEX_GATEWAY_JSON_FLAG || '--experimental-json';
const EXTRA_ARGS = (process.env.CODEX_GATEWAY_EXTRA_ARGS || '')
  .split(/\s+/)
  .filter(Boolean);
const CODEX_HOME_PATH = process.env.CODEX_GATEWAY_CODEX_HOME
  || process.env.CODEX_HOME
  || process.env.HOME
  || '/opt/codex-home';
const DEFAULT_SESSION_ROOTS = [
  path.join(process.cwd(), '.codex-gateway-sessions'),
  path.join(CODEX_HOME_PATH, 'sessions', 'gateway'),
];

function normalizeDirs(list) {
  const seen = new Set();
  const result = [];
  for (const entry of list) {
    if (!entry) {
      continue;
    }
    const resolved = path.resolve(entry);
    if (seen.has(resolved)) {
      continue;
    }
    seen.add(resolved);
    result.push(resolved);
  }
  return result;
}

const SESSION_DIRS = (() => {
  const candidates = [];
  const multi = process.env.CODEX_GATEWAY_SESSION_DIRS;
  if (multi && multi.trim().length > 0) {
    candidates.push(...multi.split(',').map((entry) => entry.trim()).filter(Boolean));
  }
  if (process.env.CODEX_GATEWAY_SESSION_DIR) {
    candidates.push(process.env.CODEX_GATEWAY_SESSION_DIR);
  }
  if (candidates.length === 0) {
    candidates.push(...DEFAULT_SESSION_ROOTS);
  }
  const legacy = path.join(process.cwd(), '.codex-gateway-sessions');
  candidates.push(legacy);
  return normalizeDirs(candidates);
})();

const PRIMARY_SESSION_DIR = SESSION_DIRS[0];
const SECURE_SESSION_DIR = path.resolve(
  process.env.CODEX_GATEWAY_SECURE_SESSION_DIR
  || path.join(process.cwd(), '.codex-gateway-sessions', 'secure'),
);
const SECURE_SESSION_TOKEN = process.env.CODEX_GATEWAY_SECURE_TOKEN || null;
const MAX_BODY_BYTES = parseInt(process.env.CODEX_GATEWAY_MAX_BODY_BYTES || '1048576', 10);
const DEFAULT_TAIL_LINES = parseInt(process.env.CODEX_GATEWAY_DEFAULT_TAIL_LINES || '200', 10);
const MAX_TAIL_LINES = parseInt(process.env.CODEX_GATEWAY_MAX_TAIL_LINES || '2000', 10);
const SIGNAL_CONTEXT_CHARS = parseInt(process.env.CODEX_GATEWAY_SIGNAL_CONTEXT || '160', 10);

// Optional file-watcher configuration (serve mode can emit completions on file events)
const WATCH_PATHS = (() => {
  const raw = process.env.CODEX_GATEWAY_WATCH_PATHS || '';
  if (!raw.trim()) return [];
  return raw.split(/[;,]/).map((s) => s.trim()).filter(Boolean).map((p) => path.resolve(p));
})();
const WATCH_PATTERN = process.env.CODEX_GATEWAY_WATCH_PATTERN || '**/*';
const WATCH_PROMPT_FILE = process.env.CODEX_GATEWAY_WATCH_PROMPT_FILE || null;
const WATCH_DEBOUNCE_MS = parseInt(process.env.CODEX_GATEWAY_WATCH_DEBOUNCE_MS || '750', 10);
const WATCH_USE_WATCHDOG = process.env.CODEX_GATEWAY_WATCH_USE_WATCHDOG === 'true';
const WATCH_SKIP_INITIAL_SCAN = /^(1|true|on)$/i.test(process.env.CODEX_GATEWAY_WATCH_SKIP_INITIAL_SCAN || 'true');
const PRUNE_BAD_SESSIONS = /^(1|true|on)$/i.test(process.env.CODEX_GATEWAY_PRUNE_BAD_SESSIONS || 'true');
const DISABLE_DEFAULT_SYSTEM_PROMPT = /^(1|true|on)$/i.test(process.env.CODEX_DISABLE_DEFAULT_PROMPT || '');
const DEFAULT_SYSTEM_PROMPT_PATH = path.resolve(process.env.CODEX_SYSTEM_PROMPT_FILE
  ? process.env.CODEX_SYSTEM_PROMPT_FILE
  : path.join(process.cwd(), 'PROMPT.md'));
const WATCH_STATUS = {
  enabled: false,
  paths: [],
  pattern: WATCH_PATTERN,
  prompt_file: WATCH_PROMPT_FILE,
  debounce_ms: WATCH_DEBOUNCE_MS,
  poll_ms: parseInt(process.env.CODEX_GATEWAY_WATCH_POLL_MS || '1000', 10),
  watcher_count: 0,
  raw_env: {
    CODEX_GATEWAY_WATCH_PATHS: process.env.CODEX_GATEWAY_WATCH_PATHS || '',
    CODEX_GATEWAY_WATCH_PATTERN: process.env.CODEX_GATEWAY_WATCH_PATTERN || '',
    CODEX_GATEWAY_WATCH_PROMPT_FILE: WATCH_PROMPT_FILE || '',
    CODEX_GATEWAY_WATCH_DEBOUNCE_MS: process.env.CODEX_GATEWAY_WATCH_DEBOUNCE_MS || '',
    CODEX_GATEWAY_WATCH_POLL_MS: process.env.CODEX_GATEWAY_WATCH_POLL_MS || '',
  },
};

// Optional generic session webhook configuration
const SESSION_WEBHOOK_URL = process.env.SESSION_WEBHOOK_URL || null;
const SESSION_WEBHOOK_TIMEOUT_MS = parseInt(process.env.SESSION_WEBHOOK_TIMEOUT_MS || '5000', 10);
const SESSION_WEBHOOK_AUTH_BEARER = process.env.SESSION_WEBHOOK_AUTH_BEARER || null;
const SESSION_WEBHOOK_HEADERS = (() => {
  const raw = process.env.SESSION_WEBHOOK_HEADERS_JSON;
  if (!raw) return null;
  try {
    const obj = JSON.parse(raw);
    return obj && typeof obj === 'object' ? obj : null;
  } catch {
    return null;
  }
})();

const WEBHOOK_STATUS = (() => {
  const url = SESSION_WEBHOOK_URL || '';
  const tail = url
    ? (url.length <= 18 ? url : `…${url.slice(-18)}`)
    : null;
  return {
    configured: Boolean(url),
    url_tail: tail,
    timeout_ms: SESSION_WEBHOOK_TIMEOUT_MS,
    has_auth_bearer: Boolean(SESSION_WEBHOOK_AUTH_BEARER),
    header_keys: SESSION_WEBHOOK_HEADERS ? Object.keys(SESSION_WEBHOOK_HEADERS) : [],
  };
})();

let triggerSchedulerManager = null;

// =============================================================================
// Concurrency Limiter - Hard limit on concurrent Codex runs
// Returns 429 (Too Many Requests) when at capacity instead of queuing forever
// =============================================================================
const MAX_CONCURRENT_CODEX = parseInt(process.env.CODEX_GATEWAY_MAX_CONCURRENT || '2', 10);

// Retry configuration for failed/empty Codex runs
// Set MAX_RETRIES=0 to disable retries (default now for faster debugging)
const MAX_RETRIES = parseInt(process.env.CODEX_GATEWAY_MAX_RETRIES || '0', 10);
const RETRY_BASE_DELAY_MS = parseInt(process.env.CODEX_GATEWAY_RETRY_DELAY_MS || '2000', 10);
const RETRY_ON_EMPTY = process.env.CODEX_GATEWAY_RETRY_ON_EMPTY === 'true'; // disabled by default

class ConcurrencyLimiter {
  constructor(maxConcurrent) {
    this.maxConcurrent = maxConcurrent;
    this.active = 0;
  }

  tryAcquire() {
    if (this.active >= this.maxConcurrent) {
      console.log(`[codex-gateway] concurrency: REJECTED (active: ${this.active}/${this.maxConcurrent})`);
      return false;
    }
    this.active++;
    console.log(`[codex-gateway] concurrency: acquired (active: ${this.active}/${this.maxConcurrent})`);
    return true;
  }

  release() {
    this.active = Math.max(0, this.active - 1);
    console.log(`[codex-gateway] concurrency: released (active: ${this.active}/${this.maxConcurrent})`);
  }

  getStatus() {
    return {
      active: this.active,
      max: this.maxConcurrent,
      available: this.maxConcurrent - this.active,
    };
  }
}

const concurrencyLimiter = new ConcurrencyLimiter(MAX_CONCURRENT_CODEX);

// Legacy throttler interface for spawn staggering (simplified - just tracks for logging)
class SpawnThrottler {
  constructor() {
    this.active = 0;
    this.lastSpawnAt = 0;
  }
  async acquire() {
    // Stagger spawns to reduce MCP cold-start contention (gnosis-crawl, etc.)
    const now = Date.now();
    const elapsed = now - this.lastSpawnAt;
    const minGapMs = parseInt(process.env.CODEX_GATEWAY_SPAWN_MIN_GAP_MS || '8000', 10);
    if (elapsed < minGapMs) {
      await new Promise((resolve) => setTimeout(resolve, minGapMs - elapsed));
    }
    this.active++;
  }
  release() {
    this.active = Math.max(0, this.active - 1);
    this.lastSpawnAt = Date.now();
  }
}

const spawnThrottler = new SpawnThrottler();

// =============================================================================
// Modular Logger - Control verbosity via CODEX_GATEWAY_LOG_LEVEL
// Levels: 0=errors only, 1=info (default), 2=verbose, 3=debug (all)
// =============================================================================
const LOG_LEVEL = parseInt(process.env.CODEX_GATEWAY_LOG_LEVEL || '1', 10);
const LOG_PREFIX = '[codex-gateway]';

function ts() {
  return new Date().toISOString();
}

const logger = {
  // Always log errors
  error: (...args) => console.error(ts(), LOG_PREFIX, ...args),
  warn: (...args) => console.warn(ts(), LOG_PREFIX, ...args),

  // Info level (level >= 1) - basic operational logs
  info: (...args) => { if (LOG_LEVEL >= 1) console.log(ts(), LOG_PREFIX, ...args); },

  // Verbose level (level >= 2) - detailed event/tool tracing
  verbose: (...args) => { if (LOG_LEVEL >= 2) console.log(ts(), LOG_PREFIX, ...args); },

  // Debug level (level >= 3) - everything including raw data
  debug: (...args) => { if (LOG_LEVEL >= 3) console.log(ts(), LOG_PREFIX, ...args); },

  // Formatted verbose logs for specific event types
  event: (type, details) => {
    if (LOG_LEVEL < 2) return;
    console.log(ts(), `${LOG_PREFIX} >>> ${type}:`, details);
  },

  // Tool call logging with emoji indicators
  toolStart: (server, tool, args) => {
    if (LOG_LEVEL < 2) return;
    console.log(`${LOG_PREFIX} 🔧 TOOL CALL STARTED:`);
    console.log(`${LOG_PREFIX}   Server: ${server}`);
    console.log(`${LOG_PREFIX}   Tool: ${tool}`);
    if (args && LOG_LEVEL >= 3) {
      const argsStr = typeof args === 'string' ? args : JSON.stringify(args);
      console.log(`${LOG_PREFIX}   Arguments:`, argsStr.slice(0, 500) + (argsStr.length > 500 ? '...' : ''));
    }
  },

  toolEnd: (server, tool, status, result, error) => {
    if (LOG_LEVEL < 2) return;
    const emoji = status === 'success' ? '✅' : status === 'error' ? '❌' : '🔧';
    console.log(`${LOG_PREFIX} ${emoji} TOOL CALL COMPLETED:`);
    console.log(`${LOG_PREFIX}   Server: ${server}`);
    console.log(`${LOG_PREFIX}   Tool: ${tool}`);
    console.log(`${LOG_PREFIX}   Status: ${status}`);
    if (error) console.error(`${LOG_PREFIX}   ERROR:`, error);
    if (result && LOG_LEVEL >= 3) {
      const resultStr = typeof result === 'string' ? result : JSON.stringify(result);
      if (resultStr.length <= 1000) {
        console.log(`${LOG_PREFIX}   Result:`, resultStr);
      } else {
        console.log(`${LOG_PREFIX}   Result (preview):`, resultStr.slice(0, 500) + '...');
        console.log(`${LOG_PREFIX}   Result (length):`, resultStr.length, 'chars');
      }
    }
  },

  // Special logging for gnosis-crawl
  crawl: (action, url, details) => {
    if (LOG_LEVEL < 2) return;
    console.log(`${LOG_PREFIX} 🔍 GNOSIS-CRAWL ${action}:`, url);
    if (details && LOG_LEVEL >= 3) {
      console.log(`${LOG_PREFIX} 🔍 GNOSIS-CRAWL details:`, details);
    }
  },

  // Agent message logging
  agentMessage: (messageId, text, isComplete) => {
    if (LOG_LEVEL < 2) return;
    const emoji = isComplete ? '💬' : '...';
    console.log(`${LOG_PREFIX} ${emoji} AGENT MESSAGE${isComplete ? ' COMPLETED' : ''}:`);
    if (messageId) console.log(`${LOG_PREFIX} ${emoji}   ID: ${messageId}`);
    console.log(`${LOG_PREFIX} ${emoji}   Length: ${text?.length || 0} chars`);
    if (LOG_LEVEL >= 3 && text) {
      if (text.length <= 1000) {
        console.log(`${LOG_PREFIX} ${emoji}   Content: ${text}`);
      } else {
        console.log(`${LOG_PREFIX} ${emoji}   Content (first 500): ${text.slice(0, 500)}...`);
        console.log(`${LOG_PREFIX} ${emoji}   Content (last 300): ...${text.slice(-300)}`);
      }
    }
  },

  // Reasoning logging
  reasoning: (text) => {
    if (LOG_LEVEL < 2) return;
    console.log(`${LOG_PREFIX} 🤔 REASONING:`);
    if (text) {
      const preview = text.length > 500 ? text.slice(0, 500) + '...' : text;
      console.log(`${LOG_PREFIX} 🤔   ${preview}`);
      if (text.length > 500) console.log(`${LOG_PREFIX} 🤔   (length: ${text.length} chars)`);
    }
  },

  // MCP tools summary at end of run
  mcpSummary: (mcpTools) => {
    if (LOG_LEVEL < 2 || !mcpTools || mcpTools.length === 0) return;
    console.log(`${LOG_PREFIX} ========================================`);
    console.log(`${LOG_PREFIX} 📋 MCP TOOLS CALLED SUMMARY:`);
    mcpTools.forEach((t, idx) => {
      const emoji = t.status === 'success' ? '✅' : t.status === 'error' ? '❌' : '🔧';
      console.log(`${LOG_PREFIX}   ${idx + 1}. ${emoji} ${t.server || 'unknown'}::${t.tool || t.name || 'unknown'} (${t.status || 'unknown'})`);
    });
    console.log(`${LOG_PREFIX} ========================================`);

    // Warnings for expected tools not called
    const hasCrawl = mcpTools.some(t => (t.tool || t.name || '').includes('crawl'));
    if (!hasCrawl && LOG_LEVEL >= 2) {
      console.warn(`${LOG_PREFIX} ⚠️  No gnosis-crawl tool calls detected`);
    }
  },

  // Session info logging
  sessionInfo: (gatewayId, codexId) => {
    if (LOG_LEVEL < 1) return;
    console.log(`${LOG_PREFIX} SESSION INFO:`);
    console.log(`${LOG_PREFIX}   Gateway Session ID: ${gatewayId}`);
    console.log(`${LOG_PREFIX}   Codex Thread ID: ${codexId || 'none'}`);
    if (codexId) {
      console.log(`${LOG_PREFIX}   Access via: /sessions/${gatewayId} or /sessions/${codexId}`);
    }
  },

  // Thread lifecycle
  threadStarted: (threadId) => {
    if (LOG_LEVEL < 2) return;
    console.log(`${LOG_PREFIX} >>> Thread started, ID: ${threadId}`);
  },

  turnStarted: () => {
    if (LOG_LEVEL < 2) return;
    console.log(`${LOG_PREFIX} >>> Turn started - AI is processing...`);
  },

  turnCompleted: () => {
    if (LOG_LEVEL < 2) return;
    console.log(`${LOG_PREFIX} >>> Turn completed`);
  },

  taskComplete: (message) => {
    if (LOG_LEVEL < 2) return;
    console.log(`${LOG_PREFIX} >>> TASK COMPLETE`);
    if (message && LOG_LEVEL >= 3) {
      console.log(`${LOG_PREFIX} >>> Final message:`, message.slice(0, 300));
    }
  },
};

function loadDefaultSystemPrompt() {
  if (DISABLE_DEFAULT_SYSTEM_PROMPT) {
    logger.info('system prompt disabled via CODEX_DISABLE_DEFAULT_PROMPT');
    return {
      prompt: '',
      enabled: false,
      disabled: true,
      path: null,
      reason: 'disabled',
    };
  }
  try {
    const text = fs.readFileSync(DEFAULT_SYSTEM_PROMPT_PATH, 'utf8');
    if (!text || text.trim().length === 0) {
      logger.warn(`system prompt file ${DEFAULT_SYSTEM_PROMPT_PATH} is empty`);
      return {
        prompt: '',
        enabled: false,
        disabled: false,
        path: DEFAULT_SYSTEM_PROMPT_PATH,
        reason: 'empty',
      };
    }
    logger.info(`loaded system prompt from ${DEFAULT_SYSTEM_PROMPT_PATH}`);
    return {
      prompt: text,
      enabled: true,
      disabled: false,
      path: DEFAULT_SYSTEM_PROMPT_PATH,
      reason: null,
    };
  } catch (error) {
    const logFn = process.env.CODEX_SYSTEM_PROMPT_FILE ? logger.warn : logger.verbose;
    logFn(`system prompt file ${DEFAULT_SYSTEM_PROMPT_PATH} not loaded: ${error.message}`);
    return {
      prompt: '',
      enabled: false,
      disabled: false,
      path: DEFAULT_SYSTEM_PROMPT_PATH,
      reason: 'missing',
    };
  }
}

const SYSTEM_PROMPT_STATUS = loadDefaultSystemPrompt();
const GLOBAL_SYSTEM_PROMPT = SYSTEM_PROMPT_STATUS.prompt || '';
const SYSTEM_PROMPT_META = {
  enabled: SYSTEM_PROMPT_STATUS.enabled,
  path: SYSTEM_PROMPT_STATUS.path,
  disabled: SYSTEM_PROMPT_STATUS.disabled,
  reason: SYSTEM_PROMPT_STATUS.reason,
};

// The watcher now reuses the same system prompt as the global prompt (e.g., PROMPT.md).
// We previously had a hardcoded watcher-specific prompt; removing it defaults to the
// user-provided system prompt file or the built-in fallback.
const WATCH_SYSTEM_PROMPT = GLOBAL_SYSTEM_PROMPT;

// Log startup config at verbose level
if (LOG_LEVEL >= 2) {
  console.log(`${LOG_PREFIX} Logger initialized at level ${LOG_LEVEL} (0=error, 1=info, 2=verbose, 3=debug)`);
}

// Generic session webhook (best effort)
async function sendSessionWebhook(sessionId, sessionStatus, metadata = {}, metaHeaders = null) {
  if (!SESSION_WEBHOOK_URL) {
    logger.verbose('webhook not configured; skipping');
    return;
  }
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), SESSION_WEBHOOK_TIMEOUT_MS);
  try {
    const headers = { 'Content-Type': 'application/json' };
    if (SESSION_WEBHOOK_AUTH_BEARER) {
      headers.Authorization = `Bearer ${SESSION_WEBHOOK_AUTH_BEARER}`;
    }
    if (SESSION_WEBHOOK_HEADERS && typeof SESSION_WEBHOOK_HEADERS === 'object') {
      Object.entries(SESSION_WEBHOOK_HEADERS).forEach(([k, v]) => {
        if (k && v !== undefined && v !== null) headers[k] = String(v);
      });
    }
    if (metadata && metadata.webhook_token) {
      headers.Authorization = `Bearer ${metadata.webhook_token}`;
    }
    if (metaHeaders && typeof metaHeaders === 'object') {
      Object.entries(metaHeaders).forEach(([k, v]) => {
        if (k && v !== undefined && v !== null) headers[k] = String(v);
      });
    }

    const payload = {
      sessionId,
      gatewaySessionId: sessionId,
      codexSessionId: metadata.codexSessionId || null,
      status: sessionStatus?.status || 'completed',
      content: sessionStatus?.content || null,
      toolCalls: sessionStatus?.tool_calls || [],
      events: sessionStatus?.events || [],
      completedAt: new Date().toISOString(),
      metadata,
    };

    const response = await fetch(SESSION_WEBHOOK_URL, {
      method: 'POST',
      headers,
      body: JSON.stringify(payload),
      signal: controller.signal,
    });
    clearTimeout(timeoutId);

    if (!response.ok) {
      const text = await response.text().catch(() => '');
      logger.warn(`webhook returned ${response.status}: ${text}`);
    } else {
      logger.info(`webhook sent for session ${sessionId}`);
    }
  } catch (error) {
    if (error.name === 'AbortError') {
      logger.warn(`webhook timeout for session ${sessionId}`);
    } else {
      logger.warn(`webhook error for session ${sessionId}: ${error.message}`);
    }
  } finally {
    clearTimeout(timeoutId);
  }
}

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

function resolveSystemPrompt(userPrompt) {
  const base = GLOBAL_SYSTEM_PROMPT || '';
  const incoming = typeof userPrompt === 'string' ? userPrompt : '';
  if (base && incoming) {
    return `${base}\n\n${incoming}`;
  }
  if (base) {
    return base;
  }
  return incoming || '';
}

function extractCodexSessionId(events) {
  if (!Array.isArray(events)) {
    return null;
  }
  for (const entry of events) {
    if (!entry || typeof entry !== 'object') {
      continue;
    }

    // New format: check entry.session_id directly
    if (typeof entry.session_id === 'string' && entry.session_id.trim().length > 0) {
      logger.debug('extractCodexSessionId: found entry.session_id', entry.session_id);
      return entry.session_id.trim();
    }

    // New format: check entry.item.session_id
    if (entry.item && typeof entry.item.session_id === 'string' && entry.item.session_id.trim().length > 0) {
      logger.debug('extractCodexSessionId: found item.session_id', entry.item.session_id);
      return entry.item.session_id.trim();
    }

    // New format: thread.started event has session info
    if (entry.type === 'thread.started' && entry.thread_id) {
      logger.debug('extractCodexSessionId: found thread_id', entry.thread_id);
      return entry.thread_id.trim();
    }

    // Old format: entry.msg
    const msg = entry.msg;
    if (!msg) {
      continue;
    }
    if (typeof msg.session_id === 'string' && msg.session_id.trim().length > 0) {
      logger.debug('extractCodexSessionId: found msg.session_id', msg.session_id);
      return msg.session_id.trim();
    }
    if (msg.session && typeof msg.session.id === 'string' && msg.session.id.trim().length > 0) {
      logger.debug('extractCodexSessionId: found msg.session.id', msg.session.id);
      return msg.session.id.trim();
    }
  }
  logger.debug('extractCodexSessionId: no session id found in events');
  return null;
}

function summarizeToolCalls(toolCalls) {
  if (!Array.isArray(toolCalls) || toolCalls.length === 0) {
    return [];
  }
  const counts = new Map();
  for (const msg of toolCalls) {
    if (!msg || typeof msg !== 'object') {
      continue;
    }
    const name = msg.tool_name || msg.tool || msg.name || 'unknown';
    const status = msg.status || (msg.type === 'mcp_tool_call_end' ? 'completed' : 'called');
    const key = `${name}::${status}`;
    counts.set(key, (counts.get(key) || 0) + 1);
  }
  const entries = Array.from(counts.entries()).map(([key, count]) => {
    const [name, status] = key.split('::');
    return { name, status, count };
  });
  entries.sort((a, b) => b.count - a.count || a.name.localeCompare(b.name));
  return entries;
}

function logRunSummary(result) {
  const contentLen = result && result.content ? result.content.length : 0;
  const eventsLen = result && Array.isArray(result.events) ? result.events.length : 0;
  const toolsLen = result && Array.isArray(result.tool_calls) ? result.tool_calls.length : 0;
  logger.verbose(`📄 content length: ${contentLen} events: ${eventsLen} tool_calls: ${toolsLen}`);
  const summary = summarizeToolCalls(result.tool_calls);
  if (summary.length > 0) {
    const top = summary.slice(0, 8).map((entry, idx) => `${idx + 1}. 🛠 ${entry.name} (${entry.status}) x${entry.count}`);
    const truncated = summary.length > 8 ? `…+${summary.length - 8} more` : '';
    logger.verbose('🧰 tool summary:', top.join(' | '), truncated);
  }
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

function buildEnvSnapshot() {
  return {
    CODEX_UNSAFE_ALLOW_NO_SANDBOX: process.env.CODEX_UNSAFE_ALLOW_NO_SANDBOX || '<unset>',
    CODEX_GATEWAY_SESSION_DIRS: process.env.CODEX_GATEWAY_SESSION_DIRS || '<unset>',
  };
}

function extractSecureToken(req, url) {
  const headerToken = req && (req.headers['x-codex-secure-token'] || req.headers['x-secure-token']);
  if (headerToken && typeof headerToken === 'string') {
    return headerToken.trim();
  }
  if (url) {
    const qp = url.searchParams.get('secure_token');
    if (qp) {
      return qp.trim();
    }
  }
  return null;
}

function hasSecureAccess(req, url) {
  if (!SECURE_SESSION_TOKEN) {
    return true;
  }
  const provided = extractSecureToken(req, url);
  return typeof provided === 'string' && provided === SECURE_SESSION_TOKEN;
}

function enforceSecureAccess(meta, req, res, url) {
  if (meta && meta.secure && !hasSecureAccess(req, url)) {
    sendError(res, 403, 'Secure session requires a valid token');
    return false;
  }
  return true;
}

const DEFAULT_TRIGGER_FILE = process.env.CODEX_GATEWAY_TRIGGER_FILE
  || path.join(process.cwd(), '.codex-monitor-triggers.json');
const DISABLE_TRIGGER_SCHEDULER = parseBoolean(process.env.CODEX_GATEWAY_DISABLE_TRIGGERS);
const TRIGGER_WATCH_DEBOUNCE_MS = parseInt(process.env.CODEX_GATEWAY_TRIGGER_DEBOUNCE_MS || '750', 10);
const MIN_TRIGGER_DELAY_MS = 250;
const SESSION_TRIGGER_ROOT = path.join(CODEX_HOME_PATH, 'sessions');
const EXTRA_TRIGGER_FILES = (process.env.CODEX_GATEWAY_TRIGGER_FILES || '')
  .split(',')
  .map((entry) => entry.trim())
  .filter(Boolean)
  .map((entry) => path.resolve(entry));

async function readTriggerConfig(triggerFile = DEFAULT_TRIGGER_FILE) {
  const resolved = path.resolve(triggerFile || DEFAULT_TRIGGER_FILE);
  try {
    const raw = await fsp.readFile(resolved, 'utf8');
    const parsed = JSON.parse(raw);
    const triggers = Array.isArray(parsed.triggers) ? parsed.triggers : [];
    return { config: { ...parsed, triggers }, file: resolved };
  } catch (error) {
    if (error.code === 'ENOENT') {
      return { config: { triggers: [] }, file: resolved };
    }
    throw error;
  }
}

async function writeTriggerConfig(triggerFile, config) {
  const resolved = path.resolve(triggerFile || DEFAULT_TRIGGER_FILE);
  ensureDirSync(path.dirname(resolved));
  const toWrite = {
    ...config,
    triggers: Array.isArray(config.triggers) ? config.triggers : [],
    updated_at: config.updated_at || new Date().toISOString(),
  };
  await fsp.writeFile(resolved, `${JSON.stringify(toWrite, null, 2)}\n`, 'utf8');
  return resolved;
}

function resolveTriggerFilePath(url) {
  if (url && typeof url.searchParams === 'object') {
    const override = url.searchParams.get('trigger_file') || url.searchParams.get('file');
    if (override && override.trim().length > 0) {
      return path.resolve(override.trim());
    }
  }
  return DEFAULT_TRIGGER_FILE;
}

function buildNormalizedTrigger(entry = {}) {
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
    last_status: entry.last_status || null,
    last_error: entry.last_error || null,
    last_attempt_at: entry.last_attempt_at || null,
    overdue: Boolean(entry.overdue) || false,
  };
  return normalized;
}

class SessionStore {
  constructor(primaryDir, extraDirs = [], secureDir) {
    const candidates = normalizeDirs([primaryDir, ...(Array.isArray(extraDirs) ? extraDirs : [])]);
    const writable = [];
    for (const dir of candidates) {
      try {
        ensureDirSync(dir);
        writable.push(dir);
      } catch (error) {
        logger.error(`unable to ensure session dir ${dir}:`, error.message);
      }
    }
    this.primaryDir = writable[0] || primaryDir;
    this.extraDirs = writable.slice(1);
    const secureFallback = path.join(process.cwd(), '.codex-gateway-secure-sessions');
    this.secureDir = secureDir || this.primaryDir;
    try {
      ensureDirSync(this.secureDir);
    } catch (error) {
      logger.error(`unable to ensure secure session dir ${this.secureDir}:`, error.message);
      this.secureDir = secureFallback;
      ensureDirSync(this.secureDir);
    }
    this.sessions = new Map();
    this.sessionRoots = new Map();
    this.codexIndex = new Map();
    this.ready = this.loadExisting();
  }

  async loadExisting() {
    try {
      const roots = [this.primaryDir, ...this.extraDirs, this.secureDir].filter(Boolean);
      const seen = new Set();
      for (const root of roots) {
        ensureDirSync(root);
        let entries = [];
        try {
          entries = await fsp.readdir(root, { withFileTypes: true });
        } catch (error) {
          logger.error('unable to load sessions:', error.message);
          continue;
        }
        for (const entry of entries) {
          if (!entry.isDirectory() || !entry.name.startsWith('session-')) {
            continue;
          }
          const sessionId = entry.name.replace(/^session-/, '');
          if (seen.has(sessionId)) {
            continue;
          }
          const metaPath = this.metaPath(sessionId, root);
          try {
            const metaRaw = await fsp.readFile(metaPath, 'utf8');
            const meta = JSON.parse(metaRaw);
            if (meta && meta.session_id) {
              meta.secure = Boolean(meta.secure) || path.resolve(root) === path.resolve(this.secureDir);
              this.sessions.set(meta.session_id, meta);
              this.sessionRoots.set(meta.session_id, root);
              seen.add(sessionId);
              if (meta.codex_session_id) {
                this.codexIndex.set(meta.codex_session_id, meta.session_id);
              }
            }
          } catch (error) {
            logger.error(`failed to load session ${sessionId}:`, error.message);
            if (PRUNE_BAD_SESSIONS) {
              const sessionDir = path.join(root, entry.name);
              try {
                await fsp.rm(sessionDir, { recursive: true, force: true });
                logger.warn(`pruned unreadable session ${sessionId} at ${sessionDir}`);
              } catch (rmError) {
                logger.warn(`unable to prune bad session ${sessionId} at ${sessionDir}: ${rmError.message}`);
              }
            }
          }
        }
      }
    } catch (error) {
      logger.error('unable to load sessions:', error.message);
    }
  }

  sessionDir(sessionId) {
    const meta = this.sessions.get(sessionId);
    if (meta && meta.secure) {
      return path.join(this.secureDir, `session-${sessionId}`);
    }
    const root = this.sessionRoots.get(sessionId) || this.primaryDir;
    return path.join(root, `session-${sessionId}`);
  }

  metaPath(sessionId, overrideRoot) {
    const base = overrideRoot ? path.join(overrideRoot, `session-${sessionId}`) : this.sessionDir(sessionId);
    return path.join(base, 'meta.json');
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
    const secure = Boolean(seedMeta.secure);
    const targetRoot = secure ? this.secureDir : this.primaryDir;
    ensureDirSync(targetRoot);
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
      secure,
    };
    this.sessions.set(sessionId, meta);
    this.sessionRoots.set(sessionId, targetRoot);
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
    if (metadata && metadata.secure) {
      meta.secure = true;
      if (this.sessionRoots.get(resolved) !== this.secureDir) {
        ensureDirSync(this.secureDir);
        this.sessionRoots.set(resolved, this.secureDir);
      }
    }
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
    if (metadata.webhook_token) {
      meta.webhook_token = metadata.webhook_token;
    }
    if (metadata.webhook_headers && typeof metadata.webhook_headers === 'object') {
      meta.webhook_headers = metadata.webhook_headers;
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
      logger.error('failed to append stdout:', error.message);
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
      logger.error('failed to append stderr:', error.message);
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
      logger.error('failed to append events:', error.message);
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
      if (payload.usage) {
        run.usage = payload.usage;
      }
      if (payload.model) {
        run.model = payload.model;
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

    // Optional: send generic webhook on completed runs
    if (payload.status === 'completed') {
      sendSessionWebhook(sessionId, {
        status: 'completed',
        content: payload.content,
        tool_calls: payload.tool_calls || [],
        events: payload.events || [],
      }, {
        codexSessionId: payload.codexSessionId || meta.codex_session_id,
        runId,
        webhook_token: meta.webhook_token || null,
      }, meta.webhook_headers || null).catch((err) => {
        logger.warn(`webhook call failed in finishRun: ${err.message}`);
      });
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

  async listSessions(limit, options = {}) {
    const includeSecure = options.includeSecure !== false;
    const secureOnly = options.secureOnly === true;
    const authorizedSecure = options.authorizedSecure !== false;
    const entries = Array.from(this.sessions.values()).filter((meta) => {
      if (secureOnly && !meta.secure) {
        return false;
      }
      if (meta.secure && !authorizedSecure) {
        return false;
      }
      if (!includeSecure && meta.secure) {
        return false;
      }
      return true;
    });
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
      secure: Boolean(meta.secure),
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
    meta.secure = Boolean(meta.secure);
    if (meta.secure && this.sessionRoots.get(sessionId) !== this.secureDir) {
      this.sessionRoots.set(sessionId, this.secureDir);
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

const sessionStore = new SessionStore(PRIMARY_SESSION_DIR, SESSION_DIRS.slice(1), SECURE_SESSION_DIR);
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
    this.verboseStreamLog = parseBoolean(process.env.CODEX_GATEWAY_VERBOSE_STREAM);
    this.verboseEventLog = parseBoolean(process.env.CODEX_GATEWAY_LOG_EVENTS);
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
      detached: process.platform !== 'win32', // Use process group on Unix for clean shutdown
    };
    this.startOptions = spawnOptions;
    const args = this.buildArgs(meta || {});
    logger.info('launching worker', JSON.stringify({
      session_id: this.sessionId,
      argv: ['codex', ...args],
      cwd: spawnOptions.cwd,
      env_keys: this.options.env ? Object.keys(this.options.env) : [],
      resume_codex_session_id: meta?.codex_session_id || null,
    }));
    // Acquire throttle before spawning to prevent MCP handshake timeouts from resource contention
    await spawnThrottler.acquire();
    this.starting = new Promise((resolve, reject) => {
      const child = spawn('codex', args, spawnOptions);
      this.proc = child;
      this.store.setWorkerState(this.sessionId, 'starting', { worker_pid: child.pid });
      child.stdout.on('data', (chunk) => {
        if (this.verboseStreamLog) {
          logger.debug(`stdout chunk ${chunk.length} size: ${chunk.length} bytes`);
          const preview = chunk.toString().slice(0, 200).replace(/\n/g, '\\n');
          logger.debug(`stdout content preview: "${preview}"`);
        }
        this.handleStdout(chunk);
      });
      child.stderr.on('data', (chunk) => {
        if (this.verboseStreamLog) {
          logger.debug(`stderr chunk ${chunk.length} size: ${chunk.length} bytes`);
          const preview = chunk.toString().slice(0, 200).replace(/\n/g, '\\n');
          logger.debug(`stderr content preview: "${preview}"`);
        }
        this.handleStderr(chunk);
      });
      child.on('error', (error) => {
        logger.error('worker error:', error);
        spawnThrottler.release(); // Release on spawn error
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
        // Delay release by stagger time to prevent rapid successive spawns
        spawnThrottler.release();
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
      logger.verbose(`>>> CODEX EVENT: ${summary}`);
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
    const runId = this.currentRun.runId || null;
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

    // Optional: send generic webhook on completed runs
    if (status === 'completed') {
      let metaToken = null;
      let metaHeaders = null;
      try {
        const meta = this.store.sessions.get(this.sessionId);
        if (meta) {
          metaToken = meta.webhook_token || null;
          metaHeaders = meta.webhook_headers || null;
        }
      } catch (err) {
        logger.warn(`finishCurrentRun: unable to read session metadata for webhook: ${err.message}`);
      }
      sendSessionWebhook(this.sessionId, {
        status: 'completed',
        content: result.content,
        tool_calls: result.tool_calls || [],
        events: result.events || [],
      }, {
        codexSessionId: this.codexSessionId,
        runId,
        webhook_token: metaToken,
      }, metaHeaders).catch((err) => {
        logger.warn(`webhook call failed in finishCurrentRun: ${err.message}`);
      });
    }
  }

  async stop(reason = 'stopped') {
    this.clearIdleTimer();
    if (this.proc) {
      const pid = this.proc.pid;
      try {
        // Kill the entire process group on Unix
        if (process.platform !== 'win32' && pid) {
          process.kill(-pid, 'SIGTERM');
        } else {
          this.proc.kill('SIGTERM');
        }
        // Force kill after 2 seconds if still alive
        setTimeout(() => {
          try {
            if (process.platform !== 'win32' && pid) {
              process.kill(-pid, 'SIGKILL');
            } else if (this.proc) {
              this.proc.kill('SIGKILL');
            }
          } catch (e) { /* process already dead */ }
        }, 2000);
      } catch (error) {
        logger.error('failed to stop worker:', error.message);
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
    secure: parseBoolean(payload.secure) || parseBoolean(payload.secure_session),
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

async function runCodex(prompt, model, options = {}) {
  const args = ['exec'];
  if (parseBoolean(process.env.CODEX_UNSAFE_ALLOW_NO_SANDBOX) !== false) {
    args.push('--dangerously-bypass-approvals-and-sandbox');
  }
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

  // Acquire throttle before spawning to prevent MCP handshake timeouts
  await spawnThrottler.acquire();

  logger.info('spawning codex', JSON.stringify({
    argv: ['codex', ...args],
    cwd,
  }));

  return new Promise((resolve, reject) => {
    const proc = spawn('codex', args, {
      cwd,
      env,
      stdio: ['pipe', 'pipe', 'pipe'],
      detached: process.platform !== 'win32', // Use process group on Unix
    });

    let stdout = '';
    let stderr = '';
    let finished = false;

    // Helper to kill the entire process tree
    const killProcessTree = () => {
      try {
        if (process.platform !== 'win32' && proc.pid) {
          // Kill the entire process group (negative PID)
          process.kill(-proc.pid, 'SIGKILL');
        } else {
          proc.kill('SIGKILL');
        }
      } catch (e) {
        // Process may already be dead
      }
    };

    const timer = setTimeout(() => {
      if (!finished) {
        finished = true;
        logger.warn('codex exec timed out, killing process tree');
        // First try SIGTERM
        try {
          if (process.platform !== 'win32' && proc.pid) {
            process.kill(-proc.pid, 'SIGTERM');
          } else {
            proc.kill('SIGTERM');
          }
        } catch (e) { /* ignore */ }
        // Force kill after 2 seconds if still alive
        setTimeout(killProcessTree, 2000);
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
          logger.error('onStdout handler failed:', error.message);
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
          logger.error('onStderr handler failed:', error.message);
        }
      }
    });

    proc.once('spawn', () => {
      spawnThrottler.release();
    });

    proc.on('error', (error) => {
      logger.error('codex spawn error:', error);
      spawnThrottler.release(); // Release on spawn error
      if (!finished) {
        finished = true;
        clearTimeout(timer);
        reject(error);
      }
    });

    proc.on('close', (code) => {
      logger.info('codex exited', code);
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
          usage: parsed.usage || null,
          model,
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
  let usage = null;
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

    // New format: {"type":"item.completed","item":{"type":"agent_message","text":"..."}}
    if (parsed.type && parsed.item) {
      events.push(parsed);
      const item = parsed.item;
      if (parsed.type === 'item.completed' && item.type === 'agent_message') {
        if (typeof item.text === 'string') {
          content = item.text;
        }
      }
      if (item.type === 'mcp_tool_call') {
        toolCalls.push({
          type: parsed.type === 'item.completed' ? 'mcp_tool_call_end' : 'mcp_tool_call_begin',
          server: item.server,
          tool: item.tool,
          arguments: item.arguments,
          result: item.result,
          status: item.status,
        });
      }
    }

    // New format: {"type":"turn.completed","usage":{...}}
    if (parsed.type === 'turn.completed' && parsed.usage) {
      usage = parsed.usage;
    }

    // Old format: {"msg":{"type":"agent_message","message":"..."}}
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
      if (msg.usage && typeof msg.usage === 'object') {
        usage = msg.usage;
      }
    }
    if (parsed.usage && typeof parsed.usage === 'object') {
      usage = parsed.usage;
    }
  }
  return { content, tool_calls: toolCalls, events, usage };
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
      secure: runOptions.secure,
      resume_codex_session_id: resumeSessionId,
    },
  });

  const resolvedSessionId = beginResult.sessionId;
  const runId = beginResult.runId;
  const runMeta = beginResult.meta;
  logger.info('SESSION START', {
    gateway_session_id: resolvedSessionId,
    run_id: runId,
    model: runOptions.model || null,
    timeout_ms: runOptions.timeoutMs || DEFAULT_TIMEOUT_MS,
  });
  const prompt = buildPrompt(messages, systemPrompt);

  // Retry loop for timeout/empty responses
  // Important: Share the timeout budget across all retries, don't multiply it
  const startTime = Date.now();
  const totalBudgetMs = runOptions.timeoutMs || DEFAULT_TIMEOUT_MS;
  const maxPerAttemptMs = Math.min(30000, Math.floor(totalBudgetMs / (MAX_RETRIES + 1))); // Max 30s per attempt

  let lastError = null;
  let attempt = 0;

  while (attempt <= MAX_RETRIES) {
    attempt++;

    // Check if we've exhausted time budget
    const elapsedMs = Date.now() - startTime;
    const remainingMs = totalBudgetMs - elapsedMs;
    if (remainingMs < 5000) {
      logger.warn(`time budget exhausted (${elapsedMs}ms elapsed), stopping retries`);
      break;
    }

    // Use smaller timeout for retries to fit within budget
    const attemptTimeoutMs = attempt === 1
      ? Math.min(runOptions.timeoutMs || DEFAULT_TIMEOUT_MS, remainingMs - 1000)
      : Math.min(maxPerAttemptMs, remainingMs - 1000);

    try {
      if (attempt > 1) {
        const delay = Math.min(RETRY_BASE_DELAY_MS * Math.pow(2, attempt - 2), 5000); // Cap delay at 5s
        logger.warn(`retry attempt ${attempt}/${MAX_RETRIES + 1} after ${delay}ms delay (${remainingMs}ms remaining)`);
        await new Promise(resolve => setTimeout(resolve, delay));
      }

      const result = await runCodex(prompt, runOptions.model, {
        timeoutMs: attemptTimeoutMs,
        cwd: runOptions.cwd,
        env: runOptions.env,
        resumeSessionId,
        onStdout: (chunk) => sessionStore.appendStdout(resolvedSessionId, chunk),
        onStderr: (chunk) => sessionStore.appendStderr(resolvedSessionId, chunk),
      });
      logRunSummary(result);

      // Check for empty response - might indicate MCP handshake failure
      const isEmpty = !result.content && (!result.events || result.events.length === 0);
      if (isEmpty) {
        // Debug: log raw stdout to help diagnose why parsing found nothing
        const rawPreview = result.raw ? result.raw.slice(0, 500) : '(no raw output)';
        logger.warn(`attempt ${attempt}: empty response - raw stdout preview: ${rawPreview.replace(/\n/g, '\\n')}`);
        if (RETRY_ON_EMPTY && attempt <= MAX_RETRIES) {
          lastError = new Error('Empty response from Codex (possible MCP handshake failure)');
          continue;
        }
      }

      const codexSessionId = extractCodexSessionId(result.events)
        || resumeSessionId
        || runMeta.codex_session_id
        || null;
      await sessionStore.finishRun(resolvedSessionId, runId, {
        status: 'completed',
        codexSessionId,
        content: result.content,
        events: result.events,
        usage: result.usage || null,
        model: runOptions.model || null,
      });
      return {
        session_id: resolvedSessionId,
        run_id: runId,
        codex_session_id: codexSessionId,
        content: result.content,
        tool_calls: result.tool_calls,
        events: result.events,
        status: 'completed',
        usage: result.usage || null,
        model: runOptions.model || null,
        retries: attempt - 1,
      };
    } catch (error) {
      lastError = error;
      const isTimeout = error.message && error.message.includes('timed out');

      if (attempt <= MAX_RETRIES) {
        logger.warn(`attempt ${attempt} failed: ${error.message}, will retry`);
        continue;
      }

      // Final attempt failed
      const status = isTimeout ? 'timeout' : 'error';
      await sessionStore.finishRun(resolvedSessionId, runId, {
        status,
        codexSessionId: resumeSessionId,
        error: error.message,
      });
      throw error;
    }
  }

  // Should not reach here, but handle it
  const status = lastError?.message?.includes('timed out') ? 'timeout' : 'error';
  await sessionStore.finishRun(resolvedSessionId, runId, {
    status,
    codexSessionId: resumeSessionId,
    error: lastError?.message || 'Max retries exceeded',
  });
  throw lastError || new Error('Max retries exceeded');
}

async function runPromptWithWorker({ payload, messages, systemPrompt, sessionId }) {
  await sessionStore.ready;
  const resolvedSystemPrompt = resolveSystemPrompt(systemPrompt);
  const promptPreview = extractPromptPreview(messages, resolvedSystemPrompt);

  const resolvedSessionId = sessionId ? sessionStore.resolveSessionId(sessionId) : null;
  const existingMeta = resolvedSessionId ? await sessionStore.getMeta(resolvedSessionId) : null;
  const resumeCodexSessionId = existingMeta?.codex_session_id || null;
  const effectivePayload = { ...payload, prompt_preview: promptPreview };
  if (existingMeta?.secure) {
    effectivePayload.secure = true;
  }

  const result = await executeSessionRun({
    payload: effectivePayload,
    messages,
    systemPrompt: resolvedSystemPrompt,
    sessionId: resolvedSessionId || undefined,
    resumeSessionId: resumeCodexSessionId,
  });

  return {
    gateway_session_id: result.session_id,
    run_id: result.run_id || null,
    codex_session_id: result.codex_session_id,
    status: result.status,
    content: result.content,
    tool_calls: result.tool_calls,
    events: result.events,
    usage: result.usage || null,
    model: result.model || null,
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

function globToRegex(pattern) {
  if (!pattern || pattern === '**/*') return null; // match everything
  // Very small glob helper: *, ?, ** supported (no character classes)
  let escaped = pattern.replace(/[.+^${}()|[\]\\]/g, '\\$&');
  escaped = escaped.replace(/\*\*/g, '.*');
  escaped = escaped.replace(/\*/g, '[^/]*');
  escaped = escaped.replace(/\?/g, '[^/]');
  return new RegExp(`^${escaped}$`);
}

function buildDefaultWatchPrompt(info) {
  const lines = [];
  lines.push('A file event was observed by the gateway watcher.');
  lines.push(`Event: ${info.event}`);
  lines.push(`Absolute path: ${info.path}`);
  lines.push(`Relative path: ${info.relative || '(n/a)'}`);
  if (info.mtime) {
    lines.push(`Modified: ${info.mtime.toISOString()}`);
  }
  if (info.size != null) {
    lines.push(`Size: ${info.size} bytes`);
  }
  lines.push('---');
  if (info.content) {
    lines.push('File content (truncated):');
    lines.push(info.content);
  } else {
    lines.push('No content available (binary, unreadable, or missing).');
  }
  return lines.join('\n');
}

async function setupFileWatcher(dispatchPrompt) {
  if (!WATCH_PATHS.length) {
    logger.info('watcher: no paths configured; file watching disabled');
    return;
  }

  if (WATCH_USE_WATCHDOG) {
    logger.warn('watcher: WATCH_USE_WATCHDOG requested but not implemented; falling back to fs.watch');
  }

  let promptTemplate = null;
  if (WATCH_PROMPT_FILE) {
    try {
      promptTemplate = await fsp.readFile(path.resolve(WATCH_PROMPT_FILE), 'utf8');
      logger.info('watcher: using prompt file', path.resolve(WATCH_PROMPT_FILE));
    } catch (err) {
      logger.warn(`watcher: failed to read prompt file ${WATCH_PROMPT_FILE}: ${err.message}`);
    }
  }

  const regex = globToRegex(WATCH_PATTERN);
  const debounceMs = Number.isFinite(WATCH_DEBOUNCE_MS) ? WATCH_DEBOUNCE_MS : 750;
  const timers = new Map(); // key: abs path, value: timeout

  async function handleEvent(eventType, absPath) {
    if (regex && !regex.test(absPath.replace(/\\/g, '/'))) {
      return;
    }
    // debounce per file
    if (timers.has(absPath)) {
      clearTimeout(timers.get(absPath));
    }
    timers.set(absPath, setTimeout(async () => {
      timers.delete(absPath);
      let stat = null;
      let content = null;
      try {
        stat = await fsp.stat(absPath);
        if (stat.isFile()) {
          try {
            const raw = await fsp.readFile(absPath);
            const text = raw.toString('utf8');
            content = text.length > 4000 ? `${text.slice(0, 4000)}\n...[truncated ${text.length} chars]` : text;
          } catch (err) {
            content = null;
          }
        }
      } catch (err) {
        logger.verbose(`watcher: stat failed for ${absPath}: ${err.message}`);
      }

      const rel = path.relative(process.cwd(), absPath);
      const info = {
        event: eventType,
        path: absPath,
        relative: rel && rel !== '' ? rel : null,
        mtime: stat?.mtime || null,
        size: stat?.size ?? null,
        content,
      };

      const promptText = promptTemplate
        ? promptTemplate
            .replace(/\{\{\s*event\s*\}\}/gi, info.event || '')
            .replace(/\{\{\s*path\s*\}\}/gi, info.path || '')
            .replace(/\{\{\s*relative\s*\}\}/gi, info.relative || '')
            .replace(/\{\{\s*mtime\s*\}\}/gi, info.mtime ? info.mtime.toISOString() : '')
            .replace(/\{\{\s*size\s*\}\}/gi, info.size != null ? String(info.size) : '')
            .replace(/\{\{\s*content\s*\}\}/gi, info.content || '')
        : buildDefaultWatchPrompt(info);

      const messages = [{ role: 'user', content: promptText }];
      try {
        logger.info(`watcher: dispatching event`, {
          event: info.event,
          path: info.path,
          relative: info.relative,
          size: info.size,
          prompt_preview: promptText.slice(0, 200),
          system_prompt_preview: (WATCH_SYSTEM_PROMPT || '').slice(0, 120),
          timeout_ms: DEFAULT_TIMEOUT_MS,
        });
        const result = await dispatchPrompt({
          payload: {
            model: DEFAULT_MODEL || undefined,
            timeout_ms: DEFAULT_TIMEOUT_MS,
            watch_event: {
              event: info.event,
              path: info.path,
              relative: info.relative,
            },
          },
          messages,
          systemPrompt: WATCH_SYSTEM_PROMPT,
          sessionId: null,
        });
        if (result && result.gateway_session_id) {
          logger.info('watcher: session started', {
            gateway_session_id: result.gateway_session_id,
            run_id: result.run_id || null,
            codex_session_id: result.codex_session_id || null,
          });
        }
      } catch (err) {
        logger.warn(`watcher: dispatch failed for ${absPath}: ${err.message}`);
      }
    }, debounceMs));
  }

  // Use polling for Docker bind mount compatibility (fs.watch doesn't work reliably)
  const POLL_INTERVAL = parseInt(process.env.CODEX_GATEWAY_WATCH_POLL_MS || '1000', 10);
  const fileStates = new Map(); // path -> { mtime, size }
  const initialScanDone = new Set();

  async function scanDirectory(dir) {
    const files = [];
    try {
      const entries = await fsp.readdir(dir, { withFileTypes: true });
      for (const entry of entries) {
        const fullPath = path.join(dir, entry.name);
        if (entry.isDirectory()) {
          const subFiles = await scanDirectory(fullPath);
          files.push(...subFiles);
        } else if (entry.isFile()) {
          files.push(fullPath);
        }
      }
    } catch (err) {
      // Directory might not exist or be inaccessible
    }
    return files;
  }

  async function pollDirectory(watchPath) {
    const files = await scanDirectory(watchPath);
    const seen = new Set(files);
    const isInitial = WATCH_SKIP_INITIAL_SCAN && !initialScanDone.has(watchPath);

    // Detect adds / changes
    for (const filePath of files) {
      try {
        const stat = await fsp.stat(filePath);
        const key = filePath;
        const prev = fileStates.get(key);
        const current = { mtime: stat.mtimeMs, size: stat.size };

        if (!prev) {
          fileStates.set(key, current);
          if (!isInitial) {
            handleEvent('add', filePath);
          }
        } else if (prev.mtime !== current.mtime || prev.size !== current.size) {
          fileStates.set(key, current);
          if (!isInitial) {
            handleEvent('change', filePath);
          }
        }
      } catch (err) {
        // ignore stat errors; deletion handled below
      }
    }

    // Detect deletes
    for (const key of Array.from(fileStates.keys())) {
      if (!seen.has(key)) {
        fileStates.delete(key);
        if (!isInitial) {
          handleEvent('delete', key);
        }
      }
    }

    if (WATCH_SKIP_INITIAL_SCAN && !initialScanDone.has(watchPath)) {
      initialScanDone.add(watchPath);
    }
  }

  WATCH_STATUS.enabled = true;
  WATCH_STATUS.paths = [];
  WATCH_STATUS.watcher_count = 0;

  let configured = 0;
  for (const rawPath of WATCH_PATHS) {
    const p = path.resolve(rawPath);
    if (!fs.existsSync(p)) {
      logger.warn(`watcher: path does not exist, skipping: ${p}`);
      continue;
    }
    try {
      // Initial scan to populate file states
      await pollDirectory(p);
      // Start polling interval
      setInterval(() => pollDirectory(p), POLL_INTERVAL);
      logger.info(`watcher configured (polling): path=${p}, pattern=${WATCH_PATTERN}, poll=${POLL_INTERVAL}ms, debounce=${debounceMs}ms, prompt=${WATCH_PROMPT_FILE || 'built-in'}`);
      WATCH_STATUS.paths.push(p);
      WATCH_STATUS.watcher_count += 1;
      configured += 1;
    } catch (err) {
      logger.warn(`watcher: failed to watch ${p}: ${err.message}`);
    }
  }

  if (configured === 0) {
    WATCH_STATUS.enabled = false;
    WATCH_STATUS.paths = [];
    WATCH_STATUS.watcher_count = 0;
    logger.warn('watcher: no valid paths configured; file watching not started');
  }
}

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
      logger.error('failed to enumerate session triggers:', error.message);
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
    logger.info(`trigger scheduler watching ${this.triggerFile}`);
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
      logger.error('trigger config parse error:', error.message);
      return;
    }
    const entries = Array.isArray(config.triggers) ? config.triggers : [];
    const seen = new Set();
    logger.info(`reloading ${entries.length} trigger(s) from ${this.triggerFile}`);
    for (const entry of entries) {
      try {
        const normalized = this.normalize(entry);
        seen.add(normalized.id);
        this.schedule(normalized);
      } catch (error) {
        logger.error('skipping trigger:', error.message);
      }
    }
    for (const key of Array.from(this.jobs.keys())) {
      if (!seen.has(key)) {
        this.cancel(key);
      }
    }
  }

  normalize(entry) {
    const normalized = buildNormalizedTrigger(entry);
    this.triggers.set(normalized.id, normalized);
    return normalized;
  }

  schedule(record) {
    this.cancel(record.id);
    let nextFire = null;
    const isOnce = (record.schedule && typeof record.schedule.mode === 'string'
      ? record.schedule.mode.toLowerCase() === 'once'
      : true);
    const now = new Date();

    // Overdue once triggers (enabled, never fired, past target) get exactly one immediate dispatch
    if (isOnce && record.enabled && !record.last_fired && !record.last_attempt_at) {
      try {
        const targetIso = record.schedule?.at || record.schedule?.time || record.created_at;
        const target = parseIsoDate(targetIso, 'schedule.at');
        if (target <= now) {
          record.overdue = true;
          nextFire = new Date(Date.now() + MIN_TRIGGER_DELAY_MS);
        }
      } catch (error) {
        logger.error(`trigger ${record.id} scheduling error:`, error.message);
      }
    }

    // Normal scheduling path
    if (!nextFire) {
      try {
        nextFire = computeNextTriggerFire(record, now);
      } catch (error) {
        logger.error(`trigger ${record.id} scheduling error:`, error.message);
      }
    }

    record.next_fire = nextFire ? nextFire.toISOString() : null;
    if (isOnce && record.enabled && !record.last_fired && !nextFire) {
      record.overdue = true;
    } else {
      record.overdue = false;
    }
    this.triggers.set(record.id, record);
    if (!nextFire) {
      return;
    }
    logger.info(`trigger '${record.title}' scheduled for ${nextFire.toISOString()} (${this.triggerFile})`);
    const delay = Math.max(nextFire.getTime() - Date.now(), MIN_TRIGGER_DELAY_MS);
    const timer = setTimeout(() => {
      this.execute(record.id).catch((error) => {
        logger.error(`trigger ${record.id} execution error:`, error.message);
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
    record.last_attempt_at = nowIso;
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
    logger.info('trigger dispatch', JSON.stringify({
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
        last_status: 'success',
        last_error: null,
        last_attempt_at: nowIso,
        overdue: false,
      });
      record.last_fired = nowIso;
      record.gateway_session_id = gatewaySessionId || null;
      record.last_status = 'success';
      record.last_error = null;
      record.last_attempt_at = nowIso;
      record.overdue = false;
    } catch (error) {
      logger.error(`trigger ${record.id} run failed:`, error.message);
      await this.updateTriggerRecord(record.id, {
        last_status: 'error',
        last_error: error.message,
        last_attempt_at: nowIso,
        overdue: false,
      }).catch(() => {});
      record.last_status = 'error';
      record.last_error = error.message;
      record.last_attempt_at = nowIso;
      record.overdue = false;
    } finally {
      if (this.isOneShot(record)) {
        if (runSucceeded) {
          logger.info(`removing completed one-shot trigger ${record.id}`);
          await this.removeTriggerRecord(record.id);
          this.triggers.delete(record.id);
          this.jobs.delete(record.id);
        } else {
          logger.warn(`one-shot trigger ${record.id} failed; not rescheduling`);
        }
        return;
      }

      this.schedule(record);
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
        logger.error('failed to persist trigger metadata:', error.message);
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
        logger.error('failed to remove trigger:', error.message);
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
        logger.verbose(`detected change in ${this.triggerFile} (${eventType})`);
        this.scheduleReload();
      });
    } catch (error) {
      logger.error('unable to watch trigger file:', error.message);
    }
  }

  scheduleReload() {
    if (this.debounceTimer) {
      return;
    }
    this.debounceTimer = setTimeout(() => {
      this.debounceTimer = null;
      this.reload().catch((error) => {
        logger.error('trigger reload failure:', error.message);
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
      logger.info(`trigger scheduler watching ${filePath}`);
    } catch (error) {
      logger.error(`failed to start scheduler for ${filePath}:`, error.message);
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
        logger.error('unable to watch session triggers:', error.message);
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
        logger.error('trigger refresh failure:', error.message);
      });
    }, Math.max(TRIGGER_WATCH_DEBOUNCE_MS, 250));
  }
}

async function handleCompletion(req, res) {
  const requestId = Math.random().toString(36).substring(7);
  logger.info('completion request', requestId, 'started');

  // Check concurrency limit - return 429 if at capacity
  if (!concurrencyLimiter.tryAcquire()) {
    const status = concurrencyLimiter.getStatus();
    logger.warn('request', requestId, 'rejected: at capacity', status);
    sendError(res, 429, 'Too many concurrent requests', {
      retry_after: 5,
      active: status.active,
      max: status.max,
    });
    return;
  }

  // Ensure we release the slot when done
  const releaseSlot = () => concurrencyLimiter.release();

  let body = '';
  try {
    body = await readBody(req);
    logger.verbose('request', requestId, 'body size:', body.length, 'bytes');
  } catch (error) {
    logger.error('request', requestId, 'read error:', error.message);
    releaseSlot();
    sendError(res, 413, error.message);
    return;
  }

  const parsed = safeJsonParse(body || '{}');
  if (!parsed.ok) {
    logger.error('request', requestId, 'invalid JSON');
    releaseSlot();
    sendError(res, 400, 'Invalid JSON payload');
    return;
  }
  const payload = parsed.value;
  const messages = Array.isArray(payload.messages) ? payload.messages : [];
  const systemPrompt = typeof payload.system_prompt === 'string' ? payload.system_prompt : '';
  if (messages.length === 0) {
    logger.error('request', requestId, 'no messages');
    releaseSlot();
    sendError(res, 400, 'messages array is required');
    return;
  }
  logger.verbose('request', requestId, 'messages:', messages.length, 'timeout_ms:', payload.timeout_ms || 'default');
  if (messages.length > 0 && messages[0].content) {
    logger.debug('request', requestId, 'first message preview:', messages[0].content.slice(0, 100));
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
  const secureRequested = parseBoolean(payload.secure) || parseBoolean(payload.secure_session);
  if ((secureRequested || (parentMeta && parentMeta.secure)) && !hasSecureAccess(req, null)) {
    releaseSlot();
    sendError(res, 403, 'Secure session requires a valid token');
    return;
  }
  const useWorker = Boolean(persistentFlag) || Boolean(resolvedSessionId);

  const payloadWithSecure = { ...payload };
  if (parentMeta && parentMeta.secure) {
    payloadWithSecure.secure = true;
  }

  try {
    logger.info('completion: system prompt preview', (systemPrompt || '').slice(0, 200));
    logger.info('completion: user msg preview', messages && messages[0] && messages[0].content ? messages[0].content.slice(0, 200) : '');
    logger.verbose('request', requestId, 'executing, useWorker:', useWorker);
    if (useWorker) {
      const result = await runPromptWithWorker({
        payload: payloadWithSecure,
        messages,
        systemPrompt,
        sessionId: resolvedSessionId,
      });
      logger.verbose('request', requestId, 'worker result - status:', result.status, 'content length:', result.content?.length || 0, 'events:', result.events?.length || 0);
      logger.verbose('request', requestId, 'session IDs - gateway:', result.gateway_session_id, 'codex:', result.codex_session_id);
      if (result.content) {
        logger.debug('request', requestId, 'content preview:', result.content.slice(0, 200));
      }
      logger.sessionInfo(result.gateway_session_id, result.codex_session_id);
      logRunSummary(result);
      releaseSlot();
      sendJson(res, 200, {
        ...result,
        env: buildEnvSnapshot(),
        session_url: `/sessions/${result.codex_session_id || result.gateway_session_id}`,
      });
      return;
    }

    const result = await executeSessionRun({
      payload: payloadWithSecure,
      messages,
      systemPrompt,
      sessionId: resolvedSessionId,
      resumeSessionId: codexResumeId,
    });
    logger.verbose('request', requestId, 'session run result - status:', result.status, 'content length:', result.content?.length || 0, 'events:', result.events?.length || 0);
    logger.verbose('request', requestId, 'session IDs - gateway:', result.session_id, 'codex:', result.codex_session_id);
    if (result.content) {
      logger.debug('request', requestId, 'content preview:', result.content.slice(0, 200));
    }
    logger.sessionInfo(result.session_id, result.codex_session_id);
    releaseSlot();
    sendJson(res, 200, {
      gateway_session_id: result.session_id,
      run_id: result.run_id || null,
      codex_session_id: result.codex_session_id,
      status: result.status,
      content: result.content,
      tool_calls: result.tool_calls,
      events: result.events,
      usage: result.usage || null,
      model: result.model || null,
      env: buildEnvSnapshot(),
      session_url: `/sessions/${result.codex_session_id || result.session_id}`,
    });
  } catch (error) {
    logger.error('request', requestId, 'completion error:', error.message);
    logger.error('request', requestId, 'error stack:', error.stack);
    releaseSlot();
    sendError(res, 500, error.message || 'Codex execution failed');
  }
}

async function handleSessionList(req, res, url) {
  await sessionStore.ready;
  const limitRaw = url.searchParams.get('limit');
  const limit = limitRaw ? parseInt(limitRaw, 10) : null;
  const includeSecureParam = url.searchParams.get('include_secure');
  const secureOnly = parseBoolean(url.searchParams.get('secure_only'));
  const includeSecure = includeSecureParam === null ? true : parseBoolean(includeSecureParam);
  const authorizedSecure = hasSecureAccess(req, url);
  const sessions = await sessionStore.listSessions(
    limit && !Number.isNaN(limit) ? limit : undefined,
    {
      includeSecure,
      secureOnly,
      authorizedSecure,
    },
  );
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
  if (!enforceSecureAccess(meta, req, res, url)) {
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
        logger.error('failed to read events:', error.message);
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
    secure: Boolean(meta.secure),
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
  const meta = await sessionStore.getMeta(resolvedId);
  if (meta && !enforceSecureAccess(meta, req, res, url)) {
    return;
  }
  try {
    const matches = await sessionStore.searchSession(resolvedId, query, {
      fuzzy,
      maxResults: !Number.isNaN(maxResults) && maxResults > 0 ? maxResults : 5,
      minScore: typeof minScore === 'number' && !Number.isNaN(minScore) ? minScore : undefined,
    });
    sendJson(res, 200, {
      session_id: resolvedId,
      codex_session_id: meta ? meta.codex_session_id : null,
      query,
      signals: matches,
    });
  } catch (error) {
    logger.error('search error:', error.message);
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
    logger.error('prompt body error:', error.message);
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
  if (!enforceSecureAccess(meta, req, res)) {
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
    logger.error('prompt error:', error.message);
    sendError(res, 500, error.message || 'Codex execution failed');
  }
}

async function handleSessionNudge(req, res, sessionIdentifier, url) {
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
  if (!enforceSecureAccess(meta, req, res, url)) {
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
    logger.error('nudge error:', error.message);
    sendError(res, 500, error.message || 'Codex execution failed');
  }
}

async function handleTriggerList(req, res, url) {
  const triggerFile = resolveTriggerFilePath(url);
  try {
    const { config, file } = await readTriggerConfig(triggerFile);
    sendJson(res, 200, {
      trigger_file: file,
      triggers: config.triggers,
    });
  } catch (error) {
    logger.error('trigger list error:', error.message);
    sendError(res, 500, 'Unable to read trigger configuration');
  }
}

async function handleTriggerCreate(req, res, url) {
  const triggerFile = resolveTriggerFilePath(url);
  const body = await readBody(req).catch((error) => {
    logger.error('trigger create body error:', error.message);
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
  let record;
  try {
    const input = parsed.value || {};
    record = buildNormalizedTrigger(input);
  } catch (error) {
    sendError(res, 400, error.message);
    return;
  }

  try {
    const { config } = await readTriggerConfig(triggerFile);
    if (config.triggers.some((existing) => existing.id === record.id)) {
      sendError(res, 409, `Trigger '${record.id}' already exists`);
      return;
    }
    config.triggers.push(record);
    config.updated_at = new Date().toISOString();
    await writeTriggerConfig(triggerFile, config);
    await triggerSchedulerManager?.refreshSchedulers();
    sendJson(res, 201, { trigger: record });
  } catch (error) {
    logger.error('trigger create error:', error.message);
    sendError(res, 500, 'Failed to persist trigger');
  }
}

async function handleTriggerUpdate(req, res, url, triggerId) {
  if (!triggerId) {
    sendError(res, 400, 'Trigger ID is required');
    return;
  }
  const triggerFile = resolveTriggerFilePath(url);
  const body = await readBody(req).catch((error) => {
    logger.error('trigger update body error:', error.message);
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
  const patch = parsed.value || {};
  try {
    const { config } = await readTriggerConfig(triggerFile);
    const index = config.triggers.findIndex((entry) => entry.id === triggerId);
    if (index === -1) {
      sendError(res, 404, `Trigger '${triggerId}' not found`);
      return;
    }
    const existing = config.triggers[index];
    const merged = {
      ...existing,
      ...patch,
      id: existing.id,
      created_at: existing.created_at,
    };
    const normalized = buildNormalizedTrigger(merged);
    normalized.last_fired = merged.last_fired || existing.last_fired || null;
    normalized.last_attempt_at = merged.last_attempt_at || existing.last_attempt_at || null;
    normalized.last_status = merged.last_status || existing.last_status || null;
    normalized.last_error = merged.last_error || existing.last_error || null;
    config.triggers[index] = normalized;
    config.updated_at = new Date().toISOString();
    await writeTriggerConfig(triggerFile, config);
    await triggerSchedulerManager?.refreshSchedulers();
    sendJson(res, 200, { trigger: normalized });
  } catch (error) {
    logger.error('trigger update error:', error.message);
    sendError(res, 500, 'Failed to update trigger');
  }
}

async function handleTriggerDelete(req, res, url, triggerId) {
  if (!triggerId) {
    sendError(res, 400, 'Trigger ID is required');
    return;
  }
  const triggerFile = resolveTriggerFilePath(url);
  try {
    const { config } = await readTriggerConfig(triggerFile);
    const filtered = config.triggers.filter((entry) => entry.id !== triggerId);
    if (filtered.length === config.triggers.length) {
      sendError(res, 404, `Trigger '${triggerId}' not found`);
      return;
    }
    config.triggers = filtered;
    config.updated_at = new Date().toISOString();
    await writeTriggerConfig(triggerFile, config);
    await triggerSchedulerManager?.refreshSchedulers();
    sendJson(res, 200, { trigger_id: triggerId });
  } catch (error) {
    logger.error('trigger delete error:', error.message);
    sendError(res, 500, 'Failed to delete trigger');
  }
}

if (require.main === module) {
  if (!DISABLE_TRIGGER_SCHEDULER) {
    triggerSchedulerManager = new TriggerSchedulerManager({
      defaultFile: DEFAULT_TRIGGER_FILE,
      extraFiles: EXTRA_TRIGGER_FILES,
      includeSessionTriggers: true,
      dispatchPrompt: async (options) => runPromptWithWorker(options),
    });
    triggerSchedulerManager.start().catch((error) => {
      logger.error('failed to start trigger schedulers:', error.message);
    });
  } else {
    logger.info('trigger scheduler disabled by configuration');
  }

  setupFileWatcher((options) => runPromptWithWorker(options))
    .catch((err) => logger.warn(`watcher setup failed: ${err.message}`));

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
          watcher: WATCH_STATUS,
          webhook: WEBHOOK_STATUS,
          system_prompt: SYSTEM_PROMPT_META,
          env: {
            CODEX_GATEWAY_SESSION_DIRS: (process.env.CODEX_GATEWAY_SESSION_DIRS || '').split(',').map((s) => s.trim()).filter(Boolean),
            CODEX_GATEWAY_SECURE_SESSION_DIR: process.env.CODEX_GATEWAY_SECURE_SESSION_DIR || '',
            CODEX_GATEWAY_EXTRA_ARGS: process.env.CODEX_GATEWAY_EXTRA_ARGS || '',
            CODEX_SANDBOX_NETWORK_DISABLED: process.env.CODEX_SANDBOX_NETWORK_DISABLED || '',
            CODEX_SYSTEM_PROMPT_FILE: SYSTEM_PROMPT_META.path || '',
            CODEX_DISABLE_DEFAULT_PROMPT: process.env.CODEX_DISABLE_DEFAULT_PROMPT || '',
          },
          endpoints: {
            health: '/health',
            status: '/status',
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

      if (segments.length === 1 && segments[0] === 'status' && method === 'GET') {
        const status = concurrencyLimiter.getStatus();
        sendJson(res, 200, {
          concurrency: status,
          uptime: process.uptime(),
          memory: process.memoryUsage(),
          watcher: WATCH_STATUS,
          webhook: WEBHOOK_STATUS,
          system_prompt: SYSTEM_PROMPT_META,
          env: {
            CODEX_GATEWAY_SESSION_DIRS: (process.env.CODEX_GATEWAY_SESSION_DIRS || '').split(',').map((s) => s.trim()).filter(Boolean),
            CODEX_GATEWAY_SECURE_SESSION_DIR: process.env.CODEX_GATEWAY_SECURE_SESSION_DIR || '',
            CODEX_GATEWAY_EXTRA_ARGS: process.env.CODEX_GATEWAY_EXTRA_ARGS || '',
            CODEX_SANDBOX_NETWORK_DISABLED: process.env.CODEX_SANDBOX_NETWORK_DISABLED || '',
            CODEX_SYSTEM_PROMPT_FILE: SYSTEM_PROMPT_META.path || '',
            CODEX_DISABLE_DEFAULT_PROMPT: process.env.CODEX_DISABLE_DEFAULT_PROMPT || '',
          },
        });
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
          await handleSessionNudge(req, res, sessionId, url);
          return;
        }
      }

      if (segments.length >= 1 && segments[0] === 'triggers') {
        const triggerId = segments.length >= 2 ? decodeURIComponent(segments[1]) : null;
        if (segments.length === 1) {
          if (method === 'GET') {
            await handleTriggerList(req, res, url);
            return;
          }
          if (method === 'POST') {
            await handleTriggerCreate(req, res, url);
            return;
          }
        } else if (segments.length === 2) {
          if (method === 'PATCH' || method === 'PUT') {
            await handleTriggerUpdate(req, res, url, triggerId);
            return;
          }
          if (method === 'DELETE') {
            await handleTriggerDelete(req, res, url, triggerId);
            return;
          }
        }
        sendError(res, 405, 'Unsupported trigger method');
        return;
      }

      sendError(res, 404, 'Not Found');
    } catch (error) {
      logger.error('unhandled error:', error);
      sendError(res, 500, 'Internal Server Error');
    }
  });

  server.listen(DEFAULT_PORT, DEFAULT_HOST, () => {
    logger.info(`listening on http://${DEFAULT_HOST}:${DEFAULT_PORT}`);
  });

  const shutdown = () => {
    logger.info('shutting down');
    if (triggerSchedulerManager) {
      triggerSchedulerManager.stop();
    }
    server.close(() => {
      process.exit(0);
    });
  };

  process.on('SIGINT', shutdown);
  process.on('SIGTERM', shutdown);
} else {
  module.exports = {
    parseCodexOutput,
  };
}
