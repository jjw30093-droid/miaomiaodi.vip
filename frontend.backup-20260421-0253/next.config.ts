import type { NextConfig } from "next";

const nextConfig: NextConfig = {
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
    return [
      {
        source: '/api/v1/:path*',
        destination: 'http://localhost:8000/api/v1/:path*',
      },
      {
        source: '/api/py/:path*',
        destination: 'http://localhost:8000/api/v1/:path*',
      },
    ];
  },
};

export default nextConfig;
