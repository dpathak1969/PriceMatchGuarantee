// mlClient.js - the only module that talks to the Flask ML endpoint. Isolating it means the transport,
// timeout, auth header and error mapping live in one place and can be mocked in tests.
const config = require('./config');

class MlError extends Error { // carries the HTTP status we want to return to our own client
  constructor(message, status) { super(message); this.status = status; }
}

async function predict(mlPayload) {
  let res;
  try {
    res = await fetch(`${config.mlUrl}/v1/predict`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-API-Key': config.mlApiKey }, // service-to-service auth
      body: JSON.stringify(mlPayload),
      signal: AbortSignal.timeout(config.mlTimeoutMs), // abort if the model service is slow/hung
    });
  } catch (e) { // network error or timeout: the ML service is unavailable, not the user's fault
    throw new MlError('The scoring service is temporarily unavailable. Please try again.', 503);
  }
  const body = await res.json().catch(() => ({})); // tolerate a non-JSON error page
  if (!res.ok) { // 4xx from ML means OUR payload was wrong (a bug), so report it as a bad gateway
    console.error('[ml] rejected request', res.status, JSON.stringify(body));
    throw new MlError('The scoring service could not process this claim.', 502);
  }
  return body;
}

// Lightweight readiness probe used by /api/health.
async function isHealthy() {
  try { const r = await fetch(`${config.mlUrl}/health`, { signal: AbortSignal.timeout(2000) }); return r.ok; }
  catch { return false; }
}

module.exports = { predict, isHealthy, MlError };
