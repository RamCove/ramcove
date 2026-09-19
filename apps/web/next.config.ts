import type { NextConfig } from "next";

const config: NextConfig = {
  reactStrictMode: true,
  agentRules: false,
  poweredByHeader: false,
  // Old addresses land where their content lives now. The site is read-only: miners submit with the
  // command line and validators run their own software, so the signed-in pages are gone.
  async redirects() {
    return [
      { source: "/competition", destination: "/docs/rules", permanent: false },
      { source: "/queue", destination: "/dashboard#queue", permanent: false },
      { source: "/submit", destination: "/docs#miners", permanent: false },
      { source: "/submissions", destination: "/dashboard", permanent: false },
      { source: "/validator", destination: "/docs#validators", permanent: false },
      { source: "/review", destination: "/dashboard", permanent: false },
      { source: "/operator", destination: "/status", permanent: false },
    ];
  },
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "no-referrer" },
          // Same-site framing only: other sites cannot embed RamCove, but the Docs can show our own PDF.
          { key: "X-Frame-Options", value: "SAMEORIGIN" },
          { key: "Content-Security-Policy", value: "frame-ancestors 'self'" },
        ],
      },
    ];
  },
};

export default config;
