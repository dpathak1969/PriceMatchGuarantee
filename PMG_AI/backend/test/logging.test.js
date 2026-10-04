// logging.test.js - verifies the logging mechanism end to end. It starts its OWN ML service (port 5101) and
// backend (port 4100) as child processes, with different LOG_LEVELs, drives a claim through them and
// inspects what each process actually printed to its terminal. Does not need anything else running.
const test = require('node:test');
const assert = require('node:assert/strict');
const { spawn } = require('node:child_process');
const path = require('node:path');
const fs = require('node:fs');
const os = require('node:os');

const ROOT = path.join(__dirname, '..', '..');
const PY = [path.join(ROOT, 'VENV_PMG', 'Scripts', 'python.exe'), path.join(ROOT, 'VENV_PMG', 'bin', 'python')].find(fs.existsSync) || 'python';
const ML_PORT = 5101, BE_PORT = 4100, API = `http://localhost:${BE_PORT}`;
const ANSI = /\x1b\[[0-9;]*m/g; // strip colour codes so assertions see plain text

// Start ML + backend with the given level; resolves with { ml, be, stop } where ml/be hold captured output.
async function stack(level) {
  const out = { ml: '', be: '' };
  const logDir = fs.mkdtempSync(path.join(os.tmpdir(), 'pmg-logs-')); // files written by BOTH services land here
  const env = { ...process.env, LOG_DIR: logDir, LOG_LEVEL: level, NO_COLOR: '1', ML_PORT: String(ML_PORT), ML_API_KEY: 'test-key', PORT: String(BE_PORT), ML_URL: `http://127.0.0.1:${ML_PORT}`, NODE_ENV: 'test' };
  const ml = spawn(PY, [path.join(ROOT, 'ml_service', 'serve.py')], { env });
  const be = spawn(process.execPath, [path.join(__dirname, '..', 'src', 'server.js')], { env, cwd: path.join(__dirname, '..') });
  for (const [name, p] of [['ml', ml], ['be', be]]) for (const s of [p.stdout, p.stderr]) s.on('data', (d) => { out[name] += d.toString().replace(ANSI, ''); });
  for (let i = 0; i < 60; i++) { // wait until the backend reports both components healthy
    try { if ((await fetch(`${API}/api/health`)).ok) break; } catch { /* not up yet */ }
    await new Promise((r) => setTimeout(r, 250));
  }
  return { out, logDir, stop: async () => { ml.kill(); be.kill(); await new Promise((r) => setTimeout(r, 300)); } };
}

// Log in as Alice with a recognisable password, request a claim id, submit a strong claim via the API.
async function runClaim() {
  const lr = await fetch(`${API}/api/auth/login`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email: 'alice@example.com', password: 'Passw0rd!' }) });
  const cookie = (lr.headers.get('set-cookie') || '').split(';')[0];
  const { claimId } = await (await fetch(`${API}/api/claims/draft`, { method: 'POST', headers: { cookie, 'X-Trace-Id': 'ui-test01' } })).json();
  const claim = { claimId, bookingType: 'Flight', bookingChannel: 'PTS Web', bookingAmount: 820, betterRateAmount: 690, bookingDate: '2025-01-10',
    travelStartDate: '2026-12-02', travelEndDate: '2026-12-09', vendorName: 'Expedia', betterRateUrl: 'https://competitor.example/deal/123', flexibility: 'Refundable',
    specialConsiderations: 'None', proofType: 'PDF Quote', proofClarity: 'Verified', restrictionsMatch: true, blackoutOrExcluded: false, multiSegment: false,
    familyBooking: true, passengers: 2, advisorTenure: '3to6', pointsRequested: 0, comments: 'cheaper on Expedia' };
  const fd = new FormData();
  fd.append('claim', JSON.stringify(claim));
  fd.append('proofFiles', new Blob([Buffer.from([0x89, 0x50, 0x4e, 0x47, 0, 0, 0, 0])], { type: 'image/png' }), 'p.png');
  const r = await fetch(`${API}/api/claims`, { method: 'POST', headers: { cookie, 'X-Trace-Id': claimId }, body: fd });
  return { claimId, status: r.status, body: await r.json(), cookie };
}
const settle = () => new Promise((r) => setTimeout(r, 400)); // let child processes flush their output

test('DEBUG: one claim is traceable browser->backend->ML with values, the ML model input and output', async () => {
  const s = await stack('debug');
  try {
    const { claimId, status, body } = await runClaim();
    await settle();
    assert.equal(status, 201); assert.equal(body.decision, 'APPROVE');
    const { be, ml } = s.out;
    // --- backend terminal: every step, which component is called, with what values
    for (const needle of ['STEP 3a', 'STEP 3b  validation passed', 'STEP 3c', 'STEP 3d', 'STEP 3e', 'STEP 3f  calling ML component',
      '==== ML REQUEST  (backend -> ML model) ====', '"url": "http://127.0.0.1:5101/v1/predict"', '"X-API-Key": "***"', '"BookingAmount": 820', '"LoyaltyTier": "Gold"', // trusted profile merged in
      '==== ML RESPONSE  (ML model -> backend) ==== HTTP 200', '"probabilityApproved"', '"decision": "APPROVE"', 'STEP 3g', `SUMMARY [BE] [${claimId}] CLAIM ${claimId}`, '"NumberOfPassengers": 2']) {
      assert.ok(be.includes(needle), `backend log missing: ${needle}`);
    }
    assert.ok(be.includes(`[${claimId}] claim ID generated`) || be.includes('claim ID generated'), 'claim id generation logged');
    // --- ML terminal: same trace id, the model's input features and its output
    for (const needle of [`[${claimId}] ==== ML REQUEST RECEIVED  (backend -> ML model) ====`, '"path": "/v1/predict"', '"X-API-Key": "***"', '"BookingAmount": 820', 'validation passed', 'model input:', '"rate_diff_pct"',
      'predicted P(approved)=', 'decision rule:', '==== ML RESPONSE SENT  (ML model -> backend) ==== HTTP 200 -> APPROVE', '"probabilityApproved"', `SUMMARY [ML] [${claimId}] SCORED claim=${claimId} -> APPROVE`, '"number_of_passengers": 2.0']) {
      assert.ok(ml.includes(needle), `ML log missing: ${needle}`);
    }
    // --- secrets never printed
    for (const text of [be, ml]) { assert.ok(!text.includes('Passw0rd!'), 'password leaked'); assert.ok(!text.includes('test-key'), 'API key leaked'); }
    // --- lines look like "HH:MM:SS.mmm LEVEL [COMP] [trace] msg"
    assert.match(be, /\d\d:\d\d:\d\d\.\d{3} (DEBUG|INFO |SUMMARY|ERROR) +\[BE\] \[/);
    assert.match(ml, /\d\d:\d\d:\d\d\.\d{3} (DEBUG|INFO |SUMMARY|ERROR) +\[ML\] \[/);
  } finally { await s.stop(); }
});

test('browser log feed: /api/logs prints [FE] lines, redacts secrets, rejects junk, blocks log injection', async () => {
  const s = await stack('debug');
  try {
    const post = (b) => fetch(`${API}/api/logs`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b) });
    assert.equal((await post({ level: 'info', msg: 'hello from browser', traceId: 'CLM-20261004-ABCDEF', data: { password: 'hunter2', email: 'a@b.c' } })).status, 204);
    assert.equal((await post({ level: 'nonsense', msg: 'x' })).status, 400);
    assert.equal((await post({ level: 'info', msg: 'line1\nFAKE LINE  ERROR [BE] forged' })).status, 204);
    await settle();
    const be = s.out.be;
    assert.ok(be.includes('INFO    [FE] [CLM-20261004-ABCDEF] hello from browser'), 'FE line shown with its trace id');
    assert.ok(be.includes('"email": "a@b.c"') && !be.includes('hunter2'), 'secret key redacted');
    assert.ok(be.includes('line1 FAKE LINE'), 'newline collapsed so a forged log line cannot be injected');
  } finally { await s.stop(); }
});

test('SUMMARY level: only summary + error lines, one summary per claim; ML too', async () => {
  const s = await stack('summary');
  try {
    const { claimId } = await runClaim();
    await settle();
    for (const [name, text] of Object.entries(s.out)) {
      const levels = [...text.matchAll(/^\d\d:\d\d:\d\d\.\d{3} (\w+)/gm)].map((m) => m[1]);
      assert.ok(levels.length > 0, `${name} printed nothing`);
      assert.ok(levels.every((l) => l === 'SUMMARY' || l === 'ERROR'), `${name} printed non-summary levels: ${[...new Set(levels)]}`);
    }
    assert.equal((s.out.be.match(new RegExp(`CLAIM ${claimId}`, 'g')) || []).length, 1, 'exactly one backend CLAIM summary');
    assert.equal((s.out.ml.match(new RegExp(`SCORED claim=${claimId}`, 'g')) || []).length, 1, 'exactly one ML SCORED summary');
  } finally { await s.stop(); }
});

test('ERROR level: successful claim prints nothing; a failure (ML down) prints an ERROR with trace id', async () => {
  const s = await stack('error');
  try {
    await runClaim(); await settle();
    assert.ok(!/ (DEBUG|INFO |SUMMARY) /.test(s.out.be + s.out.ml), 'nothing below ERROR printed on success');
    // stop only the ML process by pointing a new backend at a dead port: simpler = a fresh backend with wrong ML_URL
  } finally { await s.stop(); }
  const out = { be: '' };
  const env = { ...process.env, LOG_LEVEL: 'error', NO_COLOR: '1', PORT: String(BE_PORT), ML_URL: 'http://127.0.0.1:5999', NODE_ENV: 'test' };
  const be = spawn(process.execPath, [path.join(__dirname, '..', 'src', 'server.js')], { env, cwd: path.join(__dirname, '..') });
  for (const st of [be.stdout, be.stderr]) st.on('data', (d) => { out.be += d.toString().replace(ANSI, ''); });
  await new Promise((r) => setTimeout(r, 1500));
  try {
    const { claimId, status } = await runClaim(); await settle();
    assert.equal(status, 503);
    assert.match(out.be, new RegExp(`ERROR +\\[BE\\] \\[${claimId}\\] ML endpoint unreachable`));
  } finally { be.kill(); await new Promise((r) => setTimeout(r, 300)); }
});

test('INFO level already shows the full ML request + response blocks (not only debug)', async () => {
  const s = await stack('info');
  try {
    const { claimId } = await runClaim(); await settle();
    for (const n of ['==== ML REQUEST  (backend -> ML model) ====', '"BookingAmount": 820', '==== ML RESPONSE  (ML model -> backend) ====', '"decision": "APPROVE"']) assert.ok(s.out.be.includes(n), `backend (info) missing ${n}`);
    for (const n of ['==== ML REQUEST RECEIVED', '==== ML RESPONSE SENT', `[${claimId}]`]) assert.ok(s.out.ml.includes(n), `ML (info) missing ${n}`);
    assert.ok(!/ DEBUG /.test(s.out.be + s.out.ml), 'no DEBUG lines at info level');
  } finally { await s.stop(); }
});

test('log FILES: terminal lines are persisted, and ml-exchange.jsonl holds one audit record per ML call', async () => {
  const s = await stack('debug');
  try {
    const { claimId } = await runClaim(); await settle();
    const read = (f) => fs.readFileSync(path.join(s.logDir, f), 'utf8');
    const be = read('pmg-backend.log'), ml = read('pmg-ml.log'), ex = read('ml-exchange.jsonl').trim().split('\n').map((l) => JSON.parse(l));
    assert.ok(be.includes('==== ML REQUEST  (backend -> ML model) ====') && be.includes(`CLAIM ${claimId}`), 'backend file has the same lines as the terminal');
    assert.ok(ml.includes('==== ML REQUEST RECEIVED') && ml.includes(`SCORED claim=${claimId}`), 'ML file has the same lines as the terminal');
    assert.ok(!(be + ml).includes(String.fromCharCode(27) + '['), 'files contain no colour codes');
    assert.ok(!(be + ml).includes('Passw0rd!') && !(be + ml + JSON.stringify(ex)).includes('test-key'), 'no secrets in files');
    assert.equal(ex.length, 1);
    const [rec] = ex;
    assert.equal(rec.claimId, claimId); assert.equal(rec.status, 200);
    assert.equal(rec.request.body.BookingAmount, 820); assert.equal(rec.request.headers['X-API-Key'], '***');
    assert.equal(rec.response.decision, 'APPROVE'); assert.ok(rec.latencyMs >= 0 && rec.ts);
  } finally { await s.stop(); }
});
