#!/usr/bin/env node
// Simple callback sink: logs any POST body to stdout with timestamp
const http = require('http');

const PORT = process.env.CALLBACK_PORT || 8088;
const HOST = process.env.CALLBACK_BIND || '0.0.0.0';

const server = http.createServer((req, res) => {
  if (req.method !== 'POST') {
    res.writeHead(405, { 'Content-Type': 'text/plain' });
    res.end('Method Not Allowed');
    return;
  }
  let body = '';
  req.on('data', chunk => { body += chunk.toString(); });
  req.on('end', () => {
    const now = new Date().toISOString();
    console.log(`[callback] ${now} ${req.url}`);
    console.log(body);
    console.log('---');
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ status: 'ok' }));
  });
});

server.listen(PORT, HOST, () => {
  console.log(`callback server listening on http://${HOST}:${PORT}`);
});
