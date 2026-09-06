import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Same-origin proxy: the browser talks only to the frontend origin, so the
  // session cookie (SameSite=Lax) flows without CORS. The API base is the
  // Guguță API service (compose) or localhost for dev.
  async rewrites() {
    const api = process.env.GUGUTA_API_URL ?? "http://localhost:5055";
    return [{ source: "/guguta-api/:path*", destination: `${api}/:path*` }];
  },
};

export default nextConfig;
