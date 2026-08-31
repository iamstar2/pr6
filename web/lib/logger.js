// Minimal structured logger for server.js (Node side only — never imported from
// client components). Replaces bare console.log/console.error so every line
// carries a timestamp + level + consistent JSON shape instead of ad-hoc strings,
// without pulling in a dependency (Winston/Pino) for what's currently one file.
// If server.js grows real routing/business logic, swap this for Pino first.
const LEVELS = { debug: 10, info: 20, warn: 30, error: 40 };

const configuredLevel = LEVELS[(process.env.LOG_LEVEL || '').toLowerCase()] ?? LEVELS.info;

function log(level, message, context) {
  if (LEVELS[level] < configuredLevel) return;
  const line = {
    timestamp: new Date().toISOString(),
    level,
    message,
    ...(context && Object.keys(context).length ? context : {}),
  };
  const out = level === 'error' || level === 'warn' ? console.error : console.log;
  out(JSON.stringify(line));
}

module.exports = {
  debug: (message, context) => log('debug', message, context),
  info: (message, context) => log('info', message, context),
  warn: (message, context) => log('warn', message, context),
  error: (message, context) => log('error', message, context),
};
