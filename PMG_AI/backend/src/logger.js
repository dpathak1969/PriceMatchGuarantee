// logger.js - tiny structured logger shared by the whole backend (no dependency).
//
// LEVELS (lowest -> highest). Setting LOG_LEVEL shows that level AND everything above it:
//   debug   - full detail: request bodies, payloads sent to the ML model, raw responses
//   info    - one line per step: "-> calling ML", "<- ML answered 200 in 12ms"
//   summary - exactly ONE line per finished claim / key business event (good for production dashboards)
//   error   - failures only
// Default is "debug" for now; change with LOG_LEVEL=info|summary|error in backend/.env or the environment.
//
// Every line carries a component tag ([BE] here, [ML] in Flask, [FE] from the browser) and a TRACE ID.
// The trace id is the Claim ID once it exists, so grep'ing one claim id shows its whole journey.
const fs = require('fs');
const path = require('path');
const config = require('./config');

// ---- file sink: the SAME lines that go to the terminal (without colour) are appended to logs/pmg-backend.log.
// Simple size-based rotation (10 MB -> pmg-backend.log.1) so the file can never fill the disk.
fs.mkdirSync(config.logDir, { recursive: true });
const LOG_FILE = path.join(config.logDir, 'pmg-backend.log');
const MAX_BYTES = 10 * 1024 * 1024;
function appendFile(file, text) {
  try {
    if (fs.existsSync(file) && fs.statSync(file).size > MAX_BYTES) fs.renameSync(file, `${file}.1`); // rotate (keeps 1 old file)
    fs.appendFileSync(file, text);
  } catch { /* logging must never crash the app */ }
}

const LEVELS = { debug: 10, info: 20, summary: 25, error: 40 };
const COLORS = { debug: '\x1b[90m', info: '\x1b[36m', summary: '\x1b[32;1m', error: '\x1b[31;1m' }; // grey, cyan, bold green, bold red
const TAGS = { BE: '\x1b[35m', ML: '\x1b[33m', FE: '\x1b[34m' }; // component colours
const RESET = '\x1b[0m';
const useColor = !process.env.NO_COLOR && process.stdout.isTTY !== false; // NO_COLOR=1 disables colour

const threshold = LEVELS[String(config.logLevel).toLowerCase()] ?? LEVELS.debug; // unknown value -> debug

// Never print secrets, even at debug level. Matching keys are replaced with "***".
const SECRET_KEYS = /password|passwd|token|secret|authorization|cookie|api[-_]?key/i; // NOT bare "pass": it would mask NumberOfPassengers;
function redact(value, depth = 0) {
  if (depth > 6 || value === null || typeof value !== 'object') return value; // primitives pass through; stop runaway nesting
  if (Array.isArray(value)) return value.map((v) => redact(v, depth + 1));
  return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, SECRET_KEYS.test(k) ? '***' : redact(v, depth + 1)]));
}

// Core: build "HH:MM:SS.mmm LEVEL [COMP] [trace] message" (+ pretty JSON data at debug) and print it.
function write(level, component, traceId, message, data) {
  if (LEVELS[level] < threshold) return; // below the configured level -> drop
  const d = new Date(), p = (n, w = 2) => String(n).padStart(w, '0');
  const t = `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}.${p(d.getMilliseconds(), 3)}`; // LOCAL time, same as the ML terminal
  const lvl = level.toUpperCase().padEnd(7);
  const clean = String(message).replace(/[\r\n]+/g, ' '); // stop log-injection via newlines in user text
  const head = useColor
    ? `${'\x1b[90m'}${t}${RESET} ${COLORS[level]}${lvl}${RESET} ${TAGS[component] || ''}[${component}]${RESET} ${'\x1b[90m'}[${traceId || '-'}]${RESET} ${clean}`
    : `${t} ${lvl} [${component}] [${traceId || '-'}] ${clean}`;
  const body = data === undefined ? '' : `\n${JSON.stringify(redact(data), null, 2).replace(/^/gm, '    ')}`; // indented JSON block
  (level === 'error' ? console.error : console.log)(head + body); // terminal
  const plain = `${t} ${lvl} [${component}] [${traceId || '-'}] ${clean}`;
  appendFile(LOG_FILE, plain + body + '\n'); // file (always plain text)
}

// A logger bound to a component + trace id. child() re-binds the trace id (e.g. once the claim id is known).
function make(component, traceId) {
  const api = {};
  for (const lvl of Object.keys(LEVELS)) api[lvl] = (msg, data) => write(lvl, component, traceId, msg, data);
  api.child = (newTraceId, newComponent = component) => make(newComponent, newTraceId);
  api.enabled = (lvl) => LEVELS[lvl] >= threshold; // lets callers skip expensive work when debug is off
  return api;
}

module.exports = { logger: make('BE'), make, LEVELS, redact, appendFile, logDir: config.logDir };
