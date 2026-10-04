// server.js - process entry point: starts the HTTP listener and shuts down cleanly on SIGINT/SIGTERM.
const config = require('./config');
const { createApp } = require('./app');
const { logger } = require('./logger');

const server = createApp().listen(config.port, () => {
  logger.summary(`PMG backend listening on http://localhost:${config.port}  (ML endpoint: ${config.mlUrl}, log level: ${config.logLevel})`);
});

// Graceful shutdown: stop accepting new requests, let in-flight ones finish, then exit (orchestrator-friendly).
for (const sig of ['SIGINT', 'SIGTERM']) {
  process.on(sig, () => { logger.info(`${sig} received, shutting down`); server.close(() => process.exit(0)); });
}
