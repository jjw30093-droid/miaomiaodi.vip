import type { Metadata } from 'next';
import PricingBuyButton from './PricingBuyButton';

export const metadata: Metadata = {
  title: '套餐价格 · 喵弟数据研究室',
  description: '世界杯 2026 量化研报套餐：小组赛全包、淘汰赛通票、半段全包，AI 驱动赛前预测与赛后复盘。',
};

// ISR：products 价格变动频率低，60 秒重新验证
export const revalidate = 60;

const LIME   = '#baff00';
const RED    = '#ff3d54';
const BG     = 'rgba(5, 6, 16, 0.82)';
const BORDER = 'rgba(255,255,255,0.08)';

interface Product {
  id: number;
  sku: string;
  name: string;
  type: string;
  price_cents: number;
  price_yuan: number;
  currency: string;
  metadata: {
    scope?: string;
    match_count?: number;
    stage?: string;
  };
}

async function fetchPackages(): Promise<Product[]> {
  const backend = process.env.BACKEND_INTERNAL_URL || 'http://localhost:8000';
  try {
    const res = await fetch(`${backend}/api/v1/products?type=package`, {
      next: { revalidate: 60 },
    });
    if (!res.ok) return [];
    const data = await res.json();
    return data.products || [];
  } catch {
    return [];
  }
}

function scopeLabel(scope?: string): string {
  switch (scope) {
    case 'group_stage':  return '小组赛阶段';
    case 'knockout':     return '淘汰赛阶段';
    case 'full_half_1':  return '世界杯上半段';
    case 'full_half_2':  return '世界杯下半段';
    default:             return '套餐';
  }
}

export default async function PricingPage() {
  const products = await fetchPackages();

  // JSON-LD: schema.org/Product × N
  const jsonLd = {
    '@context': 'https://schema.org',
    '@graph': products.map((p) => ({
      '@type': 'Product',
      name: p.name,
      sku: p.sku,
      description: `${scopeLabel(p.metadata?.scope)} · ${p.metadata?.match_count ? `共 ${p.metadata.match_count} 场` : '完整覆盖'}`,
      offers: {
        '@type': 'Offer',
        priceCurrency: p.currency || 'CNY',
        price: p.price_yuan.toFixed(2),
        availability: 'https://schema.org/InStock',
      },
    })),
  };

  return (
    <>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}
      />
      <main className="min-h-screen px-4 py-12 md:py-20" style={{ background: '#050610' }}>
        <div className="max-w-5xl mx-auto">
          <header className="text-center mb-12 md:mb-16">
            <span
              className="inline-block px-4 py-1 rounded-full text-xs font-black uppercase tracking-widest mb-4"
              style={{
                backgroundColor: 'rgba(255,61,84,0.1)',
                border: `1px solid ${RED}`,
                color: RED,
              }}
            >
              WORLD CUP 2026
            </span>
            <h1
              className="text-4xl md:text-5xl font-black leading-tight mb-4"
              style={{ color: '#ffffff' }}
            >
              选择适合你的套餐
            </h1>
            <p
              className="text-base md:text-lg max-w-2xl mx-auto leading-relaxed"
              style={{ color: 'rgba(250,250,252,0.6)' }}
            >
              全场次量化预测 + 赛后复盘审计 · 单场 ¥29.9 起 · 套餐更划算
            </p>
          </header>

          {products.length === 0 ? (
            <div
              className="max-w-md mx-auto p-8 rounded-2xl text-center"
              style={{
                background: BG,
                border: `1px solid ${BORDER}`,
                color: 'rgba(250,250,252,0.6)',
              }}
            >
              暂无可购买的套餐，请稍后重试或联系客服
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              {products.map((p) => (
                <div
                  key={p.id}
                  className="p-7 rounded-2xl flex flex-col"
                  style={{
                    background: BG,
                    border: `1px solid ${BORDER}`,
                    backdropFilter: 'blur(24px)',
                    boxShadow: '0 12px 40px rgba(0,0,0,0.4), inset 0 1px 0 rgba(255,255,255,0.04)',
                  }}
                >
                  <div className="flex-1 mb-6">
                    <h2 className="text-xl font-black mb-2" style={{ color: '#ffffff' }}>
                      {p.name}
                    </h2>
                    <p className="text-xs uppercase tracking-widest font-bold mb-5" style={{ color: LIME }}>
                      {scopeLabel(p.metadata?.scope)}
                      {p.metadata?.match_count ? ` · ${p.metadata.match_count} 场` : ''}
                    </p>
                    <div className="flex items-baseline gap-2">
                      <span className="text-4xl font-black" style={{ color: '#ffffff' }}>
                        ¥{p.price_yuan}
                      </span>
                      <span className="text-sm" style={{ color: 'rgba(250,250,252,0.4)' }}>
                        / {p.currency || 'CNY'}
                      </span>
                    </div>
                  </div>
                  <PricingBuyButton
                    productId={p.id}
                    productName={p.name}
                    priceYuan={p.price_yuan}
                  />
                </div>
              ))}
            </div>
          )}

          <footer
            className="mt-16 text-center text-xs"
            style={{ color: 'rgba(250,250,252,0.4)' }}
          >
            * 当前为内测期，支付暂通过客服联系完成；后续接入虎皮椒 + Stripe 自助支付
          </footer>
        </div>
      </main>
    </>
  );
}
