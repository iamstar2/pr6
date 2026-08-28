/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // We run a custom server.js (http + Next + Socket.IO) so Next itself only
  // needs to render pages/assets; the /api/events/* ingress endpoints are
  // handled directly in server.js, not via Next's own API routes.
};

module.exports = nextConfig;
