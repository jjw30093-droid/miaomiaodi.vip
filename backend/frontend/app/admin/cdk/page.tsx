'use client';

import React, { useState, useEffect } from 'react';
import { useSession } from 'next-auth/react';
import { useRouter } from 'next/navigation';

export default function AdminCDKPage() {
  const { data: session, status } = useSession();
  const router = useRouter();
  
  const [count, setCount] = useState(5);
  const [quota, setQuota] = useState(1);
  const [expireDays, setExpireDays] = useState(30);
  const [loading, setLoading] = useState(false);
  const [generatedCdks, setGeneratedCdks] = useState<string[]>([]);
  const [error, setError] = useState('');

  // 极简的前端鉴权拦截
  useEffect(() => {
    if (status === 'unauthenticated' || (status === 'authenticated' && session?.user?.name !== 'admin')) {
      router.replace('/');
    }
  }, [status, session, router]);

  if (status === 'loading' || session?.user?.name !== 'admin') {
    return <div className="min-h-screen flex items-center justify-center">Loading...</div>;
  }

  const handleGenerate = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError('');
    
    try {
      const res = await fetch('/api/py/admin/generate-cdks', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          admin_username: session?.user?.name || 'admin',
          count,
          quota,
          expire_days: expireDays
        })
      });
      
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || '发卡失败');
      
      setGeneratedCdks(data.cdks);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleCopy = (code: string) => {
    navigator.clipboard.writeText(code);
    // 可选：加个轻提示，此处为了极简略过
  };

  const handleCopyAll = () => {
    navigator.clipboard.writeText(generatedCdks.join('\\n'));
  };

  return (
    <div className="min-h-screen bg-slate-50 p-4 sm:p-8 flex justify-center items-start pt-12">
      <div className="w-full max-w-md space-y-6">
        <div className="glass p-6 rounded-3xl shadow-xl bg-white/70 border border-white">
          <div className="flex items-center space-x-3 mb-6">
            <div className="w-10 h-10 bg-slate-900 rounded-xl flex items-center justify-center text-white font-bold">
              🛠️
            </div>
            <div>
              <h1 className="text-xl font-black text-slate-900">主理人发卡台</h1>
              <p className="text-xs text-slate-500 font-medium">移动端优化 / Mobile Admin</p>
            </div>
          </div>

          <form onSubmit={handleGenerate} className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-1">
                <label className="text-xs font-bold text-slate-500 uppercase">生成数量</label>
                <input 
                  type="number" min="1" max="50"
                  value={count} onChange={e => setCount(Number(e.target.value))}
                  className="w-full bg-white border border-slate-200 rounded-xl px-4 py-2 font-mono text-slate-900 focus:ring-2 focus:ring-indigo-500 outline-none"
                />
              </div>
              <div className="space-y-1">
                <label className="text-xs font-bold text-slate-500 uppercase">单卡额度</label>
                <input 
                  type="number" min="1" max="100"
                  value={quota} onChange={e => setQuota(Number(e.target.value))}
                  className="w-full bg-white border border-slate-200 rounded-xl px-4 py-2 font-mono text-slate-900 focus:ring-2 focus:ring-indigo-500 outline-none"
                />
              </div>
            </div>
            
            <div className="space-y-1">
              <label className="text-xs font-bold text-slate-500 uppercase">有效期 (天)</label>
              <input 
                type="number" min="1" max="365"
                value={expireDays} onChange={e => setExpireDays(Number(e.target.value))}
                className="w-full bg-white border border-slate-200 rounded-xl px-4 py-2 font-mono text-slate-900 focus:ring-2 focus:ring-indigo-500 outline-none"
              />
            </div>

            {error && <div className="text-red-500 text-sm font-bold bg-red-50 p-3 rounded-lg border border-red-100">{error}</div>}

            <button 
              type="submit" disabled={loading}
              className="w-full py-4 mt-2 bg-indigo-600 text-white font-black rounded-xl shadow-lg shadow-indigo-200 active:scale-[0.98] transition-all disabled:opacity-50 flex items-center justify-center space-x-2"
            >
              <span>{loading ? '生成中...' : '生 成 卡 密'}</span>
              {!loading && <span>⚡</span>}
            </button>
          </form>
        </div>

        {generatedCdks.length > 0 && (
          <div className="glass p-6 rounded-3xl shadow-xl bg-white/70 border border-white animate-in slide-in-from-bottom-4 relative">
            <div className="flex justify-between items-center mb-4">
              <h2 className="text-sm font-black text-slate-900 uppercase">生成结果 ({generatedCdks.length})</h2>
              <button onClick={handleCopyAll} className="text-xs font-bold text-indigo-600 hover:text-indigo-800 bg-indigo-50 px-3 py-1.5 rounded-lg">
                复制全部
              </button>
            </div>
            
            <div className="space-y-2 max-h-[40vh] overflow-y-auto pr-2 rounded-xl">
              {generatedCdks.map((code, idx) => (
                <div key={idx} className="flex justify-between items-center bg-white border border-slate-100 p-3 rounded-xl hover:border-indigo-200 transition-colors group">
                  <span className="font-mono text-slate-700 font-bold tracking-widest text-sm">{code}</span>
                  <button 
                    onClick={() => handleCopy(code)}
                    className="text-slate-400 group-hover:text-indigo-600 font-bold text-xs bg-slate-50 hover:bg-indigo-50 px-3 py-1.5 rounded-lg transition-colors"
                  >
                    Copy
                  </button>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
