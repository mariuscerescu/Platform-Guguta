import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Same-origin proxy: the browser talks only to the frontend origin, so the
  // session cookie (SameSite=Lax) flows without CORS. The API base is the
  // Guguță API service (compose) or localhost for dev.
  async rewrites() {
    // F19: default to the Guguță API container port (5056), not the upstream
    // demo (5055). Override with GUGUTA_API_URL per environment.
    const api = process.env.GUGUTA_API_URL ?? "http://localhost:5056";
    return [{ source: "/guguta-api/:path*", destination: `${api}/:path*` }];
  },
};

export default nextConfig;
