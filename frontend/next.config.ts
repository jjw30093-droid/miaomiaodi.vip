import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // turbopack disabled locally (node not in system PATH for Turbopack workers)
  // turbopack: { root: __dirname },
  images: {
    remotePatterns: [
      {
        protocol: 'https',
        hostname: 'www.fotmob.com',
      },
      {
        protocol: 'https',
        hostname: 'images.fotmob.com',
      },
      {
        protocol: 'https',
        hostname: '*.fotmob.com',
      },
    ],
  },
  rewrites: async () => {
    const backend = process.env.BACKEND_INTERNAL_URL || 'http://localhost:8000';
    return [
      {
        source: '/api/v1/:path*',
        destination: `${backend}/api/v1/:path*`,
      },
      {
        source: '/api/py/:path*',
        destination: `${backend}/api/v1/:path*`,
      },
    ];
  },
};

export default nextConfig;
