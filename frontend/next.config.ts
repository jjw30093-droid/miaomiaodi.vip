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
      {
        protocol: 'https',
        hostname: 'cdn.sportmonks.com',
      },
    ],
  },
  rewrites: async () => {
    const backend = process.env.BACKEND_INTERNAL_URL || 'http://localhost:8000';
    // fallback 模式：所有 route handlers（含动态路由 [id]）优先，
    // 没有匹配的才透传到 FastAPI。afterFiles 默认模式会让动态 route handler 输给 rewrite。
    return {
      beforeFiles: [],
      afterFiles: [],
      fallback: [
        { source: '/api/v1/:path*', destination: `${backend}/api/v1/:path*` },
        { source: '/api/py/:path*', destination: `${backend}/api/v1/:path*` },
      ],
    };
  },
};

export default nextConfig;
