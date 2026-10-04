// e2e.test.js - end-to-end checks across ALL THREE components (React is exercised through its API;
// backend + Flask ML are hit for real). Start the ML service and the backend first, then: npm test
const test = require('node:test');
const assert = require('node:assert/strict');

const API = process.env.API_URL || 'http://localhost:4000';
const ML = process.env.ML_URL || 'http://127.0.0.1:5001';
const PASSWORD = 'Passw0rd!';

// Log in and return the session cookie to send on later calls.
async function login(email, password = PASSWORD) {
  const r = await fetch(`${API}/api/auth/login`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password }) });
  return { status: r.status, cookie: (r.headers.get('set-cookie') || '').split(';')[0] };
}
const newClaimId = async (cookie) => (await (await fetch(`${API}/api/claims/draft`, { method: 'POST', headers: { cookie } })).json()).claimId;

// Submit a claim as multipart/form-data exactly like the browser does.
async function submit(cookie, claim, nFiles = 1) {
  const fd = new FormData();
  fd.append('claim', JSON.stringify(claim));
  for (let i = 0; i < nFiles; i++) fd.append('proofFiles', new Blob([Buffer.from([0x89, 0x50, 0x4e, 0x47, 0, 0, 0, 0])], { type: 'image/png' }), `p${i}.png`);
  const r = await fetch(`${API}/api/claims`, { method: 'POST', headers: { cookie }, body: fd });
  return { status: r.status, body: await r.json() };
}

// A strong claim (mirrors CLM-0001 from demo_claims.py) and a junk one (mirrors CLM-0002).
const strong = (claimId) => ({ claimId, bookingType: 'Flight', bookingChannel: 'PTS Web', bookingAmount: 820, betterRateAmount: 690,
  bookingDate: '2025-01-10', travelStartDate: '2026-12-02', travelEndDate: '2026-12-09', vendorName: 'Expedia', betterRateUrl: 'https://competitor.example/deal/123',
  flexibility: 'Refundable', specialConsiderations: 'None', proofType: 'PDF Quote', proofClarity: 'Verified', restrictionsMatch: true,
  blackoutOrExcluded: false, multiSegment: false, familyBooking: true, passengers: 2, advisorTenure: '3to6', pointsRequested: 0,
  comments: 'Found the exact same refundable flight cheaper on Expedia.' });
const junk = (claimId) => ({ ...strong(claimId), bookingType: 'Hotel/Lodging', bookingAmount: 540, betterRateAmount: 531, vendorName: 'Booking.com',
  betterRateUrl: '', flexibility: 'Non-Refundable', proofType: '', proofClarity: '', restrictionsMatch: false, familyBooking: false, passengers: 1, comments: 'Pretty sure it was cheaper.' });

test('ML endpoint rejects calls without the API key', async () => {
  assert.equal((await fetch(`${ML}/v1/predict`, { method: 'POST', body: '{}', headers: { 'Content-Type': 'application/json' } })).status, 401);
});
test('backend health reports ML reachable', async () => {
  const j = await (await fetch(`${API}/api/health`)).json();
  assert.deepEqual(j, { backend: 'ok', ml: 'ok' });
});
test('login: wrong password 401, unknown user 401, no cookie => protected routes 401', async () => {
  assert.equal((await login('alice@example.com', 'nope')).status, 401);
  assert.equal((await login('ghost@example.com')).status, 401);
  assert.equal((await fetch(`${API}/api/claims/options`)).status, 401);
});
test('strong claim by Alice is scored APPROVE and keeps the generated claim id', async () => {
  const { cookie } = await login('alice@example.com');
  const id = await newClaimId(cookie);
  assert.match(id, /^CLM-\d{8}-[0-9A-F]{6}$/);
  const { status, body } = await submit(cookie, strong(id));
  assert.equal(status, 201, JSON.stringify(body));
  assert.equal(body.claimId, id); // same ID end to end
  assert.equal(body.decision, 'APPROVE');
  assert.equal(body.claimAmount, 130);
});
test('claim id is single-use (replay => 409) and cannot be used by another user', async () => {
  const alice = (await login('alice@example.com')).cookie;
  const carol = (await login('carol@example.com')).cookie;
  const id = await newClaimId(alice);
  assert.equal((await submit(carol, strong(id))).status, 409); // not Carol's ID
  assert.equal((await submit(alice, strong(id))).status, 201);
  assert.equal((await submit(alice, strong(id))).status, 409); // replay
});
test('junk claim by suspended Bob is REJECTed', async () => {
  const { cookie } = await login('bob@example.com');
  const { status, body } = await submit(cookie, junk(await newClaimId(cookie)), 0);
  assert.equal(status, 201, JSON.stringify(body));
  assert.equal(body.decision, 'REJECT');
});
test('validation: competitor price >= paid price, bad vendor, missing files are all refused', async () => {
  const { cookie } = await login('alice@example.com');
  let r = await submit(cookie, { ...strong(await newClaimId(cookie)), betterRateAmount: 900 });
  assert.equal(r.status, 422); assert.ok(r.body.fields.betterRateAmount);
  r = await submit(cookie, { ...strong(await newClaimId(cookie)), vendorName: 'Evil Corp' });
  assert.equal(r.status, 422); assert.ok(r.body.fields.vendorName);
  r = await submit(cookie, strong(await newClaimId(cookie)), 0); // proof type chosen but no file
  assert.equal(r.status, 422); assert.ok(r.body.fields.proofFiles);
  r = await submit(cookie, { ...strong(await newClaimId(cookie)), loyaltyTier: 'Platinum' }); // cannot self-assign profile data
  assert.equal(r.status, 422);
});
test('history lists the user\'s own claims only', async () => {
  const { cookie } = await login('alice@example.com');
  const { claims } = await (await fetch(`${API}/api/claims`, { headers: { cookie } })).json();
  assert.ok(claims.length >= 1 && claims.every((c) => c.userId === 'u1'));
});
