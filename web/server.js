// Custom Node server: serves the Next.js app AND hosts the Socket.IO relay +
// the three HTTP ingress endpoints that rpi5/app/events.py POSTs to.
//
// Why a custom server instead of plain Next.js API routes: Socket.IO needs a
// long-lived HTTP server it can attach its WebSocket/polling transport to and
// keep a live registry of connected clients across requests. Next's built-in
// API routes are handled per-request by its own internal server and don't
// give us a handle to attach socket.io, so we run one http.Server ourselves,
// let Next handle page/asset rendering, and handle the /api/events/* ingress
// paths directly here before anything reaches Next.
const http = require('http');
const next = require('next');
const { Server: SocketIOServer } = require('socket.io');
const logger = require('./lib/logger');
const { validateEventPayload } = require('./lib/validateEvent');

const dev = process.env.NODE_ENV !== 'production';
const port = parseInt(process.env.PORT, 10) || 4000;

// Shared secret RPi5 must send as X-Internal-Token on POST /api/events/*. Blank
// disables auth (dev only) — see .env.example. Same idea as rpi5's DEVICE_API_KEY.
const INGRESS_TOKEN = process.env.INGRESS_TOKEN || '';
// Origin(s) allowed to open the Socket.IO connection / call the ingress endpoints
// from a browser. '*' (the old hardcoded default) is fine for local dev across
// ports, but should be the real dashboard origin once this is deployed anywhere
// reachable from outside your own machine.
const ALLOWED_ORIGIN = process.env.ALLOWED_ORIGIN || '*';

if (!INGRESS_TOKEN) {
  logger.warn('INGRESS_TOKEN is not set - /api/events/* is accepting UNAUTHENTICATED requests');
}
if (ALLOWED_ORIGIN === '*') {
  logger.warn('ALLOWED_ORIGIN is "*" - fine for local dev, not for anything internet-reachable');
}

const app = next({ dev });
const handle = app.getRequestHandler();

// Endpoint path -> Socket.IO event name, per the integration contract with
// rpi5/app/events.py. Bodies are re-emitted verbatim (exact passthrough).
const ROUTES = {
  '/api/events/live-frame': 'live_detection_frame',
  '/api/events/violation': 'violation_detected',
  '/api/events/cloud-status': 'cloud_upload_status',
};

// Payloads now embed a base64 JPEG (rpi5 relays its captured frame for the live
// view), so this needs real headroom — not just the few-hundred-byte metadata
// this limit was originally sized for.
const MAX_BODY_BYTES = 8 * 1024 * 1024; // 8MB

function readJsonBody(req) {
  return new Promise((resolve, reject) => {
    let size = 0;
    const chunks = [];
    req.on('data', (chunk) => {
      size += chunk.length;
      if (size > MAX_BODY_BYTES) {
        reject(Object.assign(new Error('Payload too large'), { statusCode: 413 }));
        req.destroy();
        return;
      }
      chunks.push(chunk);
    });
    req.on('end', () => {
      const raw = Buffer.concat(chunks).toString('utf8');
      if (!raw) {
        resolve({});
        return;
      }
      try {
        resolve(JSON.parse(raw));
      } catch (err) {
        reject(Object.assign(new Error('Invalid JSON body'), { statusCode: 400 }));
      }
    });
    req.on('error', reject);
  });
}

function setCorsHeaders(res) {
  res.setHeader('Access-Control-Allow-Origin', ALLOWED_ORIGIN);
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type, Authorization, X-Internal-Token');
}

function isAuthorized(req) {
  if (!INGRESS_TOKEN) return true; // auth disabled (dev mode, warned about at startup)
  return req.headers['x-internal-token'] === INGRESS_TOKEN;
}

app.prepare().then(() => {
  const server = http.createServer(async (req, res) => {
    try {
      const url = new URL(req.url, `http://${req.headers.host}`);
      const eventName = ROUTES[url.pathname];

      if (eventName) {
        setCorsHeaders(res);

        if (req.method === 'OPTIONS') {
          res.writeHead(204);
          res.end();
          return;
        }

        if (req.method !== 'POST') {
          res.writeHead(405, { 'Content-Type': 'application/json' });
          res.end(JSON.stringify({ error: 'Method not allowed' }));
          return;
        }

        if (!isAuthorized(req)) {
          logger.warn('Rejected unauthenticated ingress request', { path: url.pathname });
          res.writeHead(401, { 'Content-Type': 'application/json' });
          res.end(JSON.stringify({ error: 'Missing or invalid X-Internal-Token' }));
          return;
        }

        let payload;
        try {
          payload = await readJsonBody(req);
        } catch (err) {
          res.writeHead(err.statusCode || 400, { 'Content-Type': 'application/json' });
          res.end(JSON.stringify({ error: err.message }));
          return;
        }

        const validationError = validateEventPayload(eventName, payload);
        if (validationError) {
          logger.warn('Rejected malformed event payload', { path: url.pathname, error: validationError });
          res.writeHead(400, { 'Content-Type': 'application/json' });
          res.end(JSON.stringify({ error: validationError }));
          return;
        }

        // Exact passthrough beyond this point: re-emit the received JSON body unchanged.
        io.emit(eventName, payload);
        logger.info('Relayed event', { eventName, path: url.pathname, requestId: payload.request_id || '' });

        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ ok: true }));
        return;
      }

      if (url.pathname === '/healthz') {
        setCorsHeaders(res);
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ ok: true, connectedClients: io.engine.clientsCount }));
        return;
      }

      await handle(req, res);
    } catch (err) {
      logger.error('Request handling error', { error: err.message, stack: err.stack });
      res.writeHead(500, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ error: 'Internal server error' }));
    }
  });

  const io = new SocketIOServer(server, {
    cors: {
      origin: ALLOWED_ORIGIN,
      methods: ['GET', 'POST'],
    },
  });

  io.on('connection', (socket) => {
    try {
      logger.info('Socket.IO client connected', { socketId: socket.id, total: io.engine.clientsCount });
      socket.on('disconnect', () => {
        logger.info('Socket.IO client disconnected', { socketId: socket.id, total: io.engine.clientsCount });
      });
      socket.on('error', (err) => {
        logger.error('Socket.IO client error', { socketId: socket.id, error: err.message });
      });
    } catch (err) {
      logger.error('Error in connection handler', { error: err.message, stack: err.stack });
    }
  });

  server.listen(port, () => {
    logger.info('IoT safety web dashboard server ready', {
      url: `http://localhost:${port}`,
      env: dev ? 'development' : 'production',
      authEnabled: Boolean(INGRESS_TOKEN),
      allowedOrigin: ALLOWED_ORIGIN,
    });
    Object.entries(ROUTES).forEach(([path, evt]) => {
      logger.info('Ingress endpoint registered', { path, socketEvent: evt });
    });
  });
});
