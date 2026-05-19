import NextAuth from 'next-auth';
import CredentialsProvider from 'next-auth/providers/credentials';

export const { handlers, auth, signIn, signOut } = NextAuth({
  providers: [
    CredentialsProvider({
      name: 'Credentials',
      credentials: {
        username: { label: "Username", type: "text" },
        password: { label: "Password", type: "password" }
      },
      async authorize(credentials) {
        // 实际开发中通过调用 Python 后端验证并获取 Token:
        // const res = await fetch('http://localhost:8000/api/v1/login', { ... })
        // const data = await res.json()
        
        if (credentials?.username && credentials?.password) {
          // 向 Python 后端发起初始化请求并验证（带防刷防羊毛党逻辑）
          try {
            const res = await fetch(`${process.env.FASTAPI_URL || 'http://127.0.0.1:8000'}/api/v1/auth/init_session`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ username: credentials.username })
            });
            
            if (!res.ok) {
              const errorData = await res.json();
              throw new Error(errorData.detail || "初始化失败");
            }
          } catch (e: any) {
            console.error("Auth Init Error:", e);
            throw new Error(e.message || "登录/注册失败请重试");
          }

          const isAdmin = credentials.username === 'admin';

          return { 
            id: isAdmin ? "admin_1" : "user_" + Date.now(), 
            name: credentials.username as string, 
            email: credentials.username + "@example.com",
            accessToken: "mock_jwt_token",
            role: isAdmin ? "admin" : "user"
          } as any;
        }
        return null;
      }
    })
  ],
  callbacks: {
    async jwt({ token, user }) {
      if (user) {
        // 登录时将 Python API 返回的 Token 持久化进 JWT
        token.accessToken = (user as any).accessToken;
        token.role = (user as any).role;
      }
      return token;
    },
    async session({ session, token }) {
      // 将 Token 和角色暴露给前端 session
      (session as any).accessToken = token.accessToken;
      (session.user as any).role = token.role;
      return session;
    }
  },
  pages: {
    signIn: '/login',
  },
  session: {
    strategy: 'jwt',
  },
  secret: process.env.AUTH_SECRET || "dummy_jwt_secret_for_local_dev",
});
