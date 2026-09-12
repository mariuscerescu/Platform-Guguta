import type { NextConfig } from "next";

// Publicare sub subcale (F26): pe server platforma stă la
// https://tineri.math.md/edu-platform, deci build-ul primește
// NEXT_PUBLIC_BASE_PATH=/edu-platform. Gol în dezvoltare locală (rădăcină).
const basePath = process.env.NEXT_PUBLIC_BASE_PATH ?? "";

const nextConfig: NextConfig = {
  // Next prefixează automat rutele, activele și sursele din `rewrites` cu
  // basePath, deci mai jos scriem căile relative la rădăcina aplicației.
  basePath: basePath || undefined,
  // Chatul pe modelele gratuite poate dura 1–4 minute; proxy-ul Next taie
  // implicit la 30s („Eroare neașteptată." în UI). Aliniat cu timeoutul
  // chat total (300s) + marjă.
  experimental: {
    proxyTimeout: 320_000,
  },
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
