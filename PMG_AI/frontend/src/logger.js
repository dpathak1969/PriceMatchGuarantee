// logger.js - browser-side logger. Same four levels as the backend and ML service:
//   debug | info | summary | error   (setting a level shows it and everything above)
// Each line is (1) printed in the browser console (F12 -> Console) with a colour badge, and
// (2) shipped to POST /api/logs so it ALSO appears in the BACKEND TERMINAL tagged [FE].
// Level comes from VITE_LOG_LEVEL (frontend/.env), default "debug" for now.
// The trace id is the Claim ID once the form has one; every API call sends it as X-Trace-Id so
// browser, backend and ML lines for one claim can be matched by that id.
const LEVELS = { debug: 10, info: 20, summary: 25, error: 40 };
const STYLE = { debug: 'color:#888', info: 'color:#0aa', summary: 'color:#0a0;font-weight:bold', error: 'color:#d00;font-weight:bold' };
const SECRET = /password|passwd|token|secret|authorization|cookie|api[-_]?key/i;

const configured = String(import.meta.env.VITE_LOG_LEVEL || 'debug').toLowerCase();
const threshold = LEVELS[configured] ?? LEVELS.debug;

let traceId = `ui-${Math.random().toString(36).slice(2, 8)}`; // random until a claim id exists

// Replace secret-looking keys with *** so passwords can never reach the console or the server log.
function redact(v, depth = 0) {
  if (depth > 6 || v === null || typeof v !== 'object') return v;
  if (Array.isArray(v)) return v.map((x) => redact(x, depth + 1));
  return Object.fromEntries(Object.entries(v).map(([k, x]) => [k, SECRET.test(k) ? '***' : redact(x, depth + 1)]));
}

function emit(level, msg, data) {
  if (LEVELS[level] < threshold) return; // below the configured level -> ignore
  const clean = data === undefined ? undefined : redact(data);
  const d = new Date(), p = (n, w = 2) => String(n).padStart(w, '0');
  const t = `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}.${p(d.getMilliseconds(), 3)}`; // local time
  const args = [`%c${t} ${level.toUpperCase().padEnd(7)} [FE] [${traceId}] ${msg}`, STYLE[level]];
  if (clean !== undefined) args.push(clean);
  (level === 'error' ? console.error : console.log)(...args); // 1. browser console
  try { // 2. ship to the backend terminal; fire-and-forget, a logging failure must never break the app
    fetch('/api/logs', { method: 'POST', credentials: 'include', keepalive: true,
      headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ level, msg, data: clean, traceId }) }).catch(() => {});
  } catch { /* ignore */ }
}

export const log = {
  debug: (m, d) => emit('debug', m, d),
  info: (m, d) => emit('info', m, d),
  summary: (m, d) => emit('summary', m, d),
  error: (m, d) => emit('error', m, d),
  setTrace: (id) => { traceId = id || traceId; }, // call with the claim id once it is known
  getTrace: () => traceId,
};
