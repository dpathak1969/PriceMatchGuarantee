// server.js - process entry point: starts the HTTP listener and shuts down cleanly on SIGINT/SIGTERM.
const config = require('./config');
const { createApp } = require('./app');

const server = createApp().listen(config.port, () => {
  console.log(`PMG backend listening on http://localhost:${config.port}  (ML endpoint: ${config.mlUrl})`);
});

// Graceful shutdown: stop accepting new requests, let in-flight ones finish, then exit (orchestrator-friendly).
for (const sig of ['SIGINT', 'SIGTERM']) {
  process.on(sig, () => { console.log(`${sig} received, shutting down`); server.close(() => process.exit(0)); });
}
