import type { NextConfig } from "next";

const securityHeaders = [
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "X-Frame-Options", value: "DENY" },
  {
    key: "Permissions-Policy",
    value: "camera=(), microphone=(), geolocation=()",
  },
];

const config: NextConfig = {
  output: "standalone",
  poweredByHeader: false,
  // Permit this workstation's explicit development URLs to load Next's HMR
  // and hydration assets. This setting has no effect in production builds.
  allowedDevOrigins: ["127.0.0.1", "192.168.50.191"],
  async headers() {
    return [{ source: "/:path*", headers: securityHeaders }];
  },
};

export default config;
