// app.js - builds the Express application (routes + security middleware). Kept separate from server.js
// so tests can import the app without opening a network port.
//
// PRODUCTION FLOW for "file a claim":
//   1. POST /api/auth/login            -> bcrypt check -> JWT in an httpOnly cookie
//   2. POST /api/claims/draft          -> server issues a single-use Claim ID (shown to the customer)
//   3. POST /api/claims (multipart)    -> auth -> upload checks -> zod validation -> claim-ID check
//                                         -> build model payload (+ trusted profile) -> Flask /v1/predict
//                                         -> store -> return decision with the SAME Claim ID
const fs = require('fs');
const path = require('path');
const express = require('express');
const helmet = require('helmet');
const cors = require('cors');
const morgan = require('morgan');
const rateLimit = require('express-rate-limit');
const cookieParser = require('cookie-parser');
const jwt = require('jsonwebtoken');
const bcrypt = require('bcryptjs');
const multer = require('multer');
const { z } = require('zod');

const config = require('./config');
const options = require('./options');
const users = require('./users');
const { claimInput } = require('./schema');
const claims = require('./claims');
const ml = require('./mlClient');

const COOKIE = 'pmg_session'; // name of the httpOnly auth cookie

// ---- file upload rules: memory storage so nothing touches disk until the claim passes validation
const MAX_FILES = 5;
const upload = multer({
  storage: multer.memoryStorage(),
  limits: { files: MAX_FILES, fileSize: 5 * 1024 * 1024, fields: 40 }, // 5 MB per file
  fileFilter: (_req, file, cb) => cb(null, ['application/pdf', 'image/png', 'image/jpeg'].includes(file.mimetype)),
});
// Check the real file signature ("magic bytes"), because the browser-supplied MIME type can be faked.
const MAGIC = { 'application/pdf': [0x25, 0x50, 0x44, 0x46], 'image/png': [0x89, 0x50, 0x4e, 0x47], 'image/jpeg': [0xff, 0xd8, 0xff] };
const looksReal = (f) => MAGIC[f.mimetype].every((b, i) => f.buffer[i] === b);

function createApp() {
  const app = express();
  app.disable('x-powered-by'); // do not advertise the framework
  app.set('trust proxy', 1); // correct client IP for rate limiting when behind a reverse proxy
  app.use(helmet()); // secure HTTP headers (CSP, nosniff, frameguard, ...)
  app.use(cors({ origin: config.corsOrigins, credentials: true })); // only our own front-end origins
  app.use(express.json({ limit: '50kb' })); // small JSON bodies only
  app.use(cookieParser());
  if (process.env.NODE_ENV !== 'test') app.use(morgan(config.isProd ? 'combined' : 'dev')); // access log

  // ---- auth helpers ----------------------------------------------------------------
  // Middleware: reads the session cookie (or a Bearer token for API clients) and attaches req.user.
  const requireAuth = (req, res, next) => {
    const bearer = (req.headers.authorization || '').replace(/^Bearer /, '');
    const token = req.cookies[COOKIE] || bearer;
    try {
      const { sub } = jwt.verify(token, config.jwtSecret); // throws if tampered or expired
      req.user = users.findById(sub);
      return req.user ? next() : res.status(401).json({ error: 'Please sign in again.' });
    } catch { return res.status(401).json({ error: 'Please sign in to continue.' }); }
  };
  const publicUser = (u) => ({ id: u.id, name: u.name, email: u.email, loyaltyTier: u.profile.LoyaltyTier });

  // ---- health (no auth): used by load balancers and by us to verify all 3 components ----
  app.get('/api/health', async (_req, res) => {
    const mlOk = await ml.isHealthy();
    res.status(mlOk ? 200 : 503).json({ backend: 'ok', ml: mlOk ? 'ok' : 'unreachable' });
  });

  // ---- login: strict rate limit blunts password guessing -----------------------------
  const loginLimiter = rateLimit({ windowMs: 15 * 60 * 1000, limit: 20, standardHeaders: true, legacyHeaders: false,
    message: { error: 'Too many sign-in attempts. Try again in a few minutes.' } });
  const loginBody = z.object({ email: z.string().email().max(120), password: z.string().min(1).max(128) });

  app.post('/api/auth/login', loginLimiter, async (req, res) => {
    const parsed = loginBody.safeParse(req.body);
    if (!parsed.success) return res.status(400).json({ error: 'Enter a valid email and password.' });
    const user = users.findByEmail(parsed.data.email);
    // Always run bcrypt (against a dummy hash if the user is unknown) so timing does not reveal valid emails.
    const ok = await bcrypt.compare(parsed.data.password, user ? user.passwordHash : users.DUMMY_HASH);
    if (!user || !ok) return res.status(401).json({ error: 'Incorrect email or password.' }); // same message for both cases
    const token = jwt.sign({ sub: user.id }, config.jwtSecret, { expiresIn: config.jwtTtl });
    res.cookie(COOKIE, token, { httpOnly: true, sameSite: 'strict', secure: config.isProd, maxAge: 2 * 60 * 60 * 1000 }); // JS cannot read it => XSS-safe
    res.json({ user: publicUser(user) });
  });
  app.post('/api/auth/logout', (_req, res) => { res.clearCookie(COOKIE); res.json({ ok: true }); });
  app.get('/api/auth/me', requireAuth, (req, res) => res.json({ user: publicUser(req.user) })); // lets the UI restore a session on refresh

  // ---- claims ----------------------------------------------------------------------
  app.get('/api/claims/options', requireAuth, (_req, res) => res.json(options)); // dropdown values for the form
  app.get('/api/claims', requireAuth, (req, res) => res.json({ claims: claims.claimsForUser(req.user.id) })); // history

  // Step 2: issue the dynamic Claim ID when the customer opens the form.
  app.post('/api/claims/draft', requireAuth, (req, res) => res.json({ claimId: claims.issueClaimId(req.user.id) }));

  // Step 3: submit. multer parses the multipart body (JSON in the "claim" field + proof files).
  const submitLimiter = rateLimit({ windowMs: 60 * 1000, limit: 15, standardHeaders: true, legacyHeaders: false,
    message: { error: 'Too many submissions. Please wait a minute.' } });
  app.post('/api/claims', requireAuth, submitLimiter, upload.array('proofFiles', MAX_FILES), async (req, res) => {
    // 3a. parse the JSON the form put in the "claim" field
    let body;
    try { body = JSON.parse(req.body.claim); } catch { return res.status(400).json({ error: 'Malformed claim data.' }); }
    // 3b. validate every field (types, enums, ranges, cross-field rules)
    const parsed = claimInput.safeParse(body);
    if (!parsed.success) {
      const fields = Object.fromEntries(parsed.error.issues.map((i) => [i.path.join('.') || 'form', i.message]));
      return res.status(422).json({ error: 'Please correct the highlighted fields.', fields });
    }
    const input = parsed.data;
    // 3c. proof rules: type + clarity + files must be given together, and files must be genuine
    const files = req.files || [];
    if (files.some((f) => !looksReal(f))) return res.status(422).json({ error: 'A file is not a valid PDF, PNG or JPG.', fields: { proofFiles: 'Use PDF, PNG or JPG files' } });
    if (Boolean(input.proofType) !== files.length > 0 || (input.proofType && !input.proofClarity)) {
      return res.status(422).json({ error: 'Proof details are incomplete.', fields: { proofFiles: 'Choose a proof type, rate its clarity and attach at least one file (or remove all three).' } });
    }
    // 3d. the Claim ID must be the one we issued to THIS user and not yet used
    if (!claims.consumeClaimId(input.claimId, req.user.id)) {
      return res.status(409).json({ error: 'This claim was already submitted or the session expired. Reload the form to start a new claim.' });
    }
    try {
      // 3e. build the exact payload the model expects, merging in trusted account data
      const payload = claims.buildMlPayload(input, req.user.profile, files.length);
      // 3f. call the Flask ML endpoint
      const prediction = await ml.predict(payload);
      // 3g. persist the files (named by claim ID) and the outcome
      const dir = path.join(config.uploadDir, input.claimId);
      fs.mkdirSync(dir, { recursive: true });
      files.forEach((f, i) => fs.writeFileSync(path.join(dir, `proof-${i + 1}${{ 'application/pdf': '.pdf', 'image/png': '.png', 'image/jpeg': '.jpg' }[f.mimetype]}`), f.buffer));
      const record = { claimId: input.claimId, userId: req.user.id, submittedAt: new Date().toISOString(),
        claimAmount: payload.ClaimAmount, bookingType: input.bookingType, vendorName: input.vendorName,
        decision: prediction.decision, probabilityApproved: prediction.probabilityApproved, signals: prediction.signals };
      claims.saveClaim(record);
      // 3h. respond - the claimId in the answer is the one generated in step 2
      return res.status(201).json({ ...record, threshold: prediction.threshold, referBand: prediction.referBand });
    } catch (e) {
      claims.releaseClaimId(input.claimId); // let the customer retry with the same ID
      if (e instanceof ml.MlError) return res.status(e.status).json({ error: e.message });
      console.error(e);
      return res.status(500).json({ error: 'Unexpected error. Please try again.' });
    }
  });

  // ---- upload errors (too big, too many files) -> friendly 4xx instead of a stack trace
  app.use('/api', (err, _req, res, _next) => {
    if (err instanceof multer.MulterError) return res.status(413).json({ error: `Upload problem: ${err.message}. Max ${MAX_FILES} files of 5 MB.` });
    console.error(err);
    return res.status(500).json({ error: 'Unexpected error.' });
  });
  app.use('/api', (_req, res) => res.status(404).json({ error: 'Not found' })); // unknown API route

  // ---- serve the built React app (production: one origin, no CORS needed) ----------------
  if (fs.existsSync(config.frontendDist)) {
    app.use(express.static(config.frontendDist));
    app.get(/^(?!\/api).*/, (_req, res) => res.sendFile(path.join(config.frontendDist, 'index.html'))); // SPA fallback
  }
  return app;
}

module.exports = { createApp };
