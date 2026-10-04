// mlClient.js - the only module that talks to the Flask ML endpoint. Isolating it means the transport,
// timeout, auth header, tracing and error mapping live in one place and can be mocked in tests.
const config = require('./config');
const path = require('path');
const { logger, appendFile, redact, logDir } = require('./logger');
const EXCHANGE_FILE = path.join(logDir, 'ml-exchange.jsonl'); // one JSON line per ML call (audit trail)

class MlError extends Error { // carries the HTTP status we want to return to our own client
  constructor(message, status) { super(message); this.status = status; }
}

// log: a logger already bound to the claim's trace id (so these lines can be matched to the request).
async function predict(mlPayload, log = logger) {
  const url = `${config.mlUrl}/v1/predict`;
  const headers = { 'Content-Type': 'application/json', 'X-API-Key': config.mlApiKey, // service-to-service auth
    'X-Trace-Id': mlPayload.ClaimID || '' }; // lets the Flask logs carry the SAME trace id
  // Full detail of what we send (INFO, so it shows at the default and at "info"). The API key is masked as ***.
  log.info('==== ML REQUEST  (backend -> ML model) ====', { method: 'POST', url, headers, body: mlPayload });
  const t0 = process.hrtime.bigint();
  const audit = { ts: new Date().toISOString(), claimId: mlPayload.ClaimID, url, request: redact({ headers, body: mlPayload }) };
  let res;
  try {
    res = await fetch(url, {
      method: 'POST',
      headers,
      body: JSON.stringify(mlPayload),
      signal: AbortSignal.timeout(config.mlTimeoutMs), // abort if the model service is slow/hung
    });
  } catch (e) { // network error or timeout: the ML service is unavailable, not the user's fault
    log.error(`ML endpoint unreachable or timed out (${e.name}: ${e.message})`);
    appendFile(EXCHANGE_FILE, JSON.stringify({ ...audit, error: `${e.name}: ${e.message}` }) + '\n');
    throw new MlError('The scoring service is temporarily unavailable. Please try again.', 503);
  }
  const ms = Number(process.hrtime.bigint() - t0) / 1e6; // round-trip time in milliseconds
  const body = await res.json().catch(() => ({})); // tolerate a non-JSON error page
  appendFile(EXCHANGE_FILE, JSON.stringify({ ...audit, status: res.status, latencyMs: Math.round(ms), response: body }) + '\n'); // audit record
  if (!res.ok) { // 4xx from ML means OUR payload was wrong (a bug), so report it as a bad gateway
    log.error(`==== ML RESPONSE  (ML model -> backend) ==== HTTP ${res.status} in ${ms.toFixed(0)}ms`, body);
    throw new MlError('The scoring service could not process this claim.', 502);
  }
  log.info(`==== ML RESPONSE  (ML model -> backend) ==== HTTP ${res.status} in ${ms.toFixed(0)}ms -> ${body.decision} (P=${body.probabilityApproved})`, { status: res.status, latencyMs: Math.round(ms), body });
  return body;
}

// Lightweight readiness probe used by /api/health.
async function isHealthy() {
  try { const r = await fetch(`${config.mlUrl}/health`, { signal: AbortSignal.timeout(2000) }); return r.ok; }
  catch { return false; }
}

module.exports = { predict, isHealthy, MlError };
