import type { Metadata } from "next";
import "./globals.css";
import AuthProvider from "@/components/AuthProvider";
import { ThemeProvider } from "@/components/ThemeProvider";
import SessionRevokedProvider from "@/components/center/SessionRevokedProvider";

export const metadata: Metadata = {
  title: "足球数研所",
  description: "SaaS platform for AI-powered football match analysis reports using Dixon-Coles, LightGBM and SHAP explainability. 专业足球数据研究订阅服务。",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN" suppressHydrationWarning>
      <head>
        {/* 同步设置 dark class，防止浅色闪屏（FOUC）*/}
        <script dangerouslySetInnerHTML={{ __html: `(function(){try{var t=localStorage.getItem('theme');document.documentElement.classList.add(t==='dark'?'dark':'light');}catch(e){document.documentElement.classList.add('light');}})();` }} />
        <meta name="robots" content="index, follow, max-snippet:-1, max-image-preview:large" />
        <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: `{"@context":"https://schema.org","@graph":[{"@type":"SoftwareApplication","name":"足球数研所","url":"https://miaomiaodi.vip","applicationCategory":"SportsApplication","operatingSystem":"Web","description":"SaaS platform for AI-powered football match analysis reports using Dixon-Coles, LightGBM and SHAP explainability.","offers":{"@type":"Offer","priceCurrency":"CNY","price":"0","description":"Free tier available; paid subscription for full access"}},{"@type":"Dataset","name":"Football Match Analysis Dataset","description":"Statistical football match data covering 10+ leagues, including Dixon-Coles probability estimates, LightGBM predictions, and SHAP feature attributions.","url":"https://miaomiaodi.vip","creator":{"@type":"Organization","name":"足球数研所"},"license":"https://miaomiaodi.vip/terms"}]}` }} />
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
      </head>
      <body className="min-h-screen bg-[var(--color-background)] text-[var(--color-foreground)]">
        <ThemeProvider>
          <AuthProvider>
            {children}
            <SessionRevokedProvider />
          </AuthProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
