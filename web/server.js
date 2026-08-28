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

const dev = process.env.NODE_ENV !== 'production';
const port = parseInt(process.env.PORT, 10) || 4000;

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
  // Allow-all-origins dev/mock-stage CORS: frontend dev server and this
  // backend run on different ports, and rpi5 may run on a different host.
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type, Authorization');
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

        let payload;
        try {
          payload = await readJsonBody(req);
        } catch (err) {
          res.writeHead(err.statusCode || 400, { 'Content-Type': 'application/json' });
          res.end(JSON.stringify({ error: err.message }));
          return;
        }

        // Exact passthrough: re-emit the received JSON body unchanged.
        io.emit(eventName, payload);
        console.log(`[events] ${eventName} <- ${url.pathname}`, payload.request_id || '');

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
      console.error('Request handling error:', err);
      res.writeHead(500, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ error: 'Internal server error' }));
    }
  });

  const io = new SocketIOServer(server, {
    cors: {
      origin: '*',
      methods: ['GET', 'POST'],
    },
  });

  io.on('connection', (socket) => {
    console.log(`[socket.io] client connected: ${socket.id} (total: ${io.engine.clientsCount})`);
    socket.on('disconnect', () => {
      console.log(`[socket.io] client disconnected: ${socket.id} (total: ${io.engine.clientsCount})`);
    });
  });

  server.listen(port, () => {
    console.log(`> IoT safety web dashboard server ready on http://localhost:${port} (${dev ? 'development' : 'production'})`);
    console.log('> Ingress endpoints:');
    Object.entries(ROUTES).forEach(([path, evt]) => {
      console.log(`    POST http://localhost:${port}${path}  ->  socket.io event "${evt}"`);
    });
  });
});
