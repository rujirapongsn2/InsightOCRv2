import type { NextConfig } from "next";

const apiRewriteOrigin =
  process.env.NEXT_API_REWRITE_ORIGIN ||
  (process.env.NODE_ENV === "development"
    ? "http://127.0.0.1:3000"
    : "http://backend:8000");

const nextConfig: NextConfig = {
  skipTrailingSlashRedirect: true,
  async rewrites() {
    return [
      {
        source: "/api/v1/jobs/",
        destination: `${apiRewriteOrigin}/api/v1/jobs/`,
      },
      {
        source: "/api/v1/schemas/",
        destination: `${apiRewriteOrigin}/api/v1/schemas/`,
      },
      {
        source: "/api/v1/activity-logs/",
        destination: `${apiRewriteOrigin}/api/v1/activity-logs/`,
      },
      {
        source: "/api/v1/integrations",
        destination: `${apiRewriteOrigin}/api/v1/integrations/`,
      },
      {
        source: "/api/v1/integrations/",
        destination: `${apiRewriteOrigin}/api/v1/integrations/`,
      },
      {
        source: "/api/v1/workflows",
        destination: `${apiRewriteOrigin}/api/v1/workflows/`,
      },
      {
        source: "/api/v1/workflows/",
        destination: `${apiRewriteOrigin}/api/v1/workflows/`,
      },
      {
        source: "/api/v1/ai-settings",
        destination: `${apiRewriteOrigin}/api/v1/ai-settings/`,
      },
      {
        source: "/api/v1/ai-settings/",
        destination: `${apiRewriteOrigin}/api/v1/ai-settings/`,
      },
      {
        source: "/api/v1/users",
        destination: `${apiRewriteOrigin}/api/v1/users/`,
      },
      {
        source: "/api/v1/users/",
        destination: `${apiRewriteOrigin}/api/v1/users/`,
      },
      {
        source: "/api/v1/users/me/api-tokens",
        destination: `${apiRewriteOrigin}/api/v1/users/me/api-tokens/`,
      },
      {
        source: "/api/v1/users/me/api-tokens/",
        destination: `${apiRewriteOrigin}/api/v1/users/me/api-tokens/`,
      },
      {
        source: "/api/v1/:path*",
        destination: `${apiRewriteOrigin}/api/v1/:path*`,
      },
    ];
  },
};

export default nextConfig;
