// config.js - single place where every environment variable is read, validated and given a default.
// Reading env vars here (and nowhere else) keeps the rest of the code testable and 12-factor compliant.
const path = require('path');
const crypto = require('crypto');
require('dotenv').config(); // load backend/.env into process.env when the file exists (ignored in real prod)

const isProd = process.env.NODE_ENV === 'production'; // production switches on stricter security below

const config = {
  isProd,
  port: Number(process.env.PORT || 4000), // port this backend listens on
  // Base URL of the Flask ML endpoint (never exposed to the browser).
  mlUrl: process.env.ML_URL || 'http://127.0.0.1:5001',
  // Shared secret sent to the ML endpoint in the X-API-Key header. Must match ML_API_KEY there.
  mlApiKey: process.env.ML_API_KEY || 'dev-ml-key-change-me',
  mlTimeoutMs: Number(process.env.ML_TIMEOUT_MS || 8000), // fail fast instead of hanging the user
  // Secret that signs login tokens (JWT). Random per start in dev; MUST be set explicitly in production.
  jwtSecret: process.env.JWT_SECRET || (isProd ? null : crypto.randomBytes(32).toString('hex')),
  jwtTtl: process.env.JWT_TTL || '2h', // how long a login lasts
  // Browser origins allowed to call the API with cookies (the React dev server by default).
  corsOrigins: (process.env.CORS_ORIGINS || 'http://localhost:5173,http://127.0.0.1:5173').split(','),
  uploadDir: process.env.UPLOAD_DIR || path.join(__dirname, '..', 'uploads'), // where proof files are stored
  dataDir: process.env.DATA_DIR || path.join(__dirname, '..', 'data'), // where the claim log is stored
  frontendDist: process.env.FRONTEND_DIST || path.join(__dirname, '..', '..', 'frontend', 'dist'), // built React app
};

// Refuse to boot in production with an unsafe configuration - failing loudly beats running insecurely.
if (isProd && (!config.jwtSecret || config.mlApiKey === 'dev-ml-key-change-me')) {
  throw new Error('Set JWT_SECRET and ML_API_KEY (non-default) when NODE_ENV=production');
}

module.exports = config;
