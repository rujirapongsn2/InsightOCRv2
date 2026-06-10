import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  skipTrailingSlashRedirect: true,
  async rewrites() {
    return [
      {
        source: "/api/v1/jobs/",
        destination: "http://backend:8000/api/v1/jobs/",
      },
      {
        source: "/api/v1/schemas/",
        destination: "http://backend:8000/api/v1/schemas/",
      },
      {
        source: "/api/v1/activity-logs/",
        destination: "http://backend:8000/api/v1/activity-logs/",
      },
      {
        source: "/api/v1/:path*",
        destination: "http://backend:8000/api/v1/:path*",
      },
    ];
  },
};

export default nextConfig;
