#!/usr/bin/env node
const http = require('http');
const { spawn } = require('child_process');

const DEFAULT_PORT = parseInt(process.env.CODEX_GATEWAY_PORT || '4000', 10);
const DEFAULT_HOST = process.env.CODEX_GATEWAY_BIND || '0.0.0.0';
const DEFAULT_TIMEOUT_MS = parseInt(process.env.CODEX_GATEWAY_TIMEOUT_MS || '120000', 10);
const DEFAULT_MODEL = process.env.CODEX_GATEWAY_DEFAULT_MODEL || '';
const EXTRA_ARGS = (process.env.CODEX_GATEWAY_EXTRA_ARGS || '')
  .split(/\s+/)
  .filter(Boolean);

function sendJson(res, statusCode, payload) {
  const body = JSON.stringify(payload);
  res.writeHead(statusCode, {
    'Content-Type': 'application/json',
    'Content-Length': Buffer.byteLength(body),
  });
  res.end(body);
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

    // Handle --json format: {id, msg}
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

function runCodex(prompt, model, options = {}) {
  return new Promise((resolve, reject) => {
    const args = ['exec', '--json', '--color=never', '--skip-git-repo-check'];
    if (model) {
      args.push('--model', model);
    }
    if (Array.isArray(EXTRA_ARGS) && EXTRA_ARGS.length > 0) {
      args.push(...EXTRA_ARGS);
    }
    args.push('-');

    const cwd = options.cwd || process.cwd();
    const timeoutMs = options.timeoutMs || DEFAULT_TIMEOUT_MS;

    const proc = spawn('codex', args, {
      cwd,
      env: process.env,
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
      stdout += chunk.toString();
    });

    proc.stderr.on('data', (chunk) => {
      stderr += chunk.toString();
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

    proc.stdin.write(prompt);
    proc.stdin.end();
  });
}

const server = http.createServer(async (req, res) => {
  const path = req.url.split('?')[0];
  const normalizedPath = path.endsWith('/') && path.length > 1 ? path.slice(0, -1) : path;

  if ((req.method === 'GET' || req.method === 'HEAD') && normalizedPath === '/health') {
    sendJson(res, 200, { status: 'ok' });
    return;
  }

  if ((req.method === 'GET' || req.method === 'HEAD') && (normalizedPath === '/' || normalizedPath === '')) {
    sendJson(res, 200, {
      status: 'codex-gateway',
      endpoints: {
        health: '/health',
        completion: {
          path: '/completion',
          method: 'POST',
          body: '{ "messages": [...] }'
        }
      }
    });
    return;
  }

  if (req.method !== 'POST' || normalizedPath !== '/completion') {
    sendJson(res, 404, { error: 'Not Found' });
    return;
  }

  let body = '';
  req.on('data', (chunk) => {
    body += chunk.toString();
    if (body.length > 1_000_000) {
      body = '';
      req.destroy(new Error('Payload too large'));
    }
  });

  req.on('error', (error) => {
    console.error('[codex-gateway] request error:', error);
  });

  req.on('end', async () => {
    let payload;
    try {
      payload = body ? JSON.parse(body) : {};
    } catch (error) {
      sendJson(res, 400, { error: 'Invalid JSON payload' });
      return;
    }

    const messages = Array.isArray(payload.messages) ? payload.messages : [];
    const systemPrompt = typeof payload.system_prompt === 'string' ? payload.system_prompt : '';
    const model = typeof payload.model === 'string' && payload.model.trim().length > 0 ? payload.model : DEFAULT_MODEL;

    if (messages.length === 0) {
      sendJson(res, 400, { error: 'messages array is required' });
      return;
    }

    const prompt = buildPrompt(messages, systemPrompt);

    try {
      const result = await runCodex(prompt, model, {
        timeoutMs: payload.timeout_ms,
        cwd: payload.cwd || process.cwd(),
      });

      sendJson(res, 200, {
        content: result.content,
        tool_calls: result.tool_calls,
        events: result.events,
      });
    } catch (error) {
      console.error('[codex-gateway] error:', error);
      sendJson(res, 500, { error: error.message || 'Codex execution failed' });
    }
  });
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
