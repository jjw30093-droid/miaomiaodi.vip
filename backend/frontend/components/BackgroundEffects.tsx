import React from 'react';

export const BackgroundEffects = () => {
  return (
    <>
      {/* Noise Texture for premium cyber feel */}
      <div className="fixed inset-0 bg-noise pointer-events-none z-0" />

      {/* High-Tech Interwoven Gradient Background */}
      <div className="fixed inset-0 overflow-hidden pointer-events-none z-0">
        {/* Deep Blue Base */}
        <div className="absolute top-[-10%] left-[-20%] w-[150vw] h-[150vw] md:w-[80vw] md:h-[80vw] bg-blue-600/30 blur-[90px] md:blur-[120px] rounded-full mix-blend-screen animate-float-slow" />
        {/* Cyan Sweep */}
        <div className="absolute top-[20%] right-[-30%] w-[120vw] h-[120vw] md:w-[70vw] md:h-[70vw] bg-primary-neon/25 blur-[80px] md:blur-[100px] rounded-full mix-blend-screen animate-float-slower" />
        {/* Magenta Sweep */}
        <div className="absolute bottom-[-10%] left-[-10%] w-[140vw] h-[140vw] md:w-[90vw] md:h-[90vw] bg-secondary-magenta/20 blur-[90px] md:blur-[130px] rounded-full mix-blend-screen animate-float-slow" style={{ animationDelay: '-5s' }} />
        {/* Purple Core */}
        <div className="absolute top-[40%] right-[10%] w-[100vw] h-[100vw] md:w-[60vw] md:h-[60vw] bg-purple-600/30 blur-[80px] md:blur-[120px] rounded-full mix-blend-screen animate-float-slower" style={{ animationDelay: '-10s' }} />
      </div>

      {/* Radar Sweep Effect */}
      <div className="fixed inset-0 overflow-hidden pointer-events-none z-0 flex items-center justify-center opacity-30">
        <div className="w-[200vw] h-[200vw] md:w-[100vw] md:h-[100vw] rounded-full border border-primary-neon/10 animate-pulse-glow" />
        <div className="absolute w-[150vw] h-[150vw] md:w-[75vw] md:h-[75vw] rounded-full border border-secondary-magenta/10 animate-pulse-glow" style={{ animationDelay: '-1.5s' }} />
        <div className="absolute w-[100vw] h-[100vw] md:w-[50vw] md:h-[50vw] rounded-full border border-blue-500/10 animate-pulse-glow" style={{ animationDelay: '-2.5s' }} />
        
        {/* Rotating Radar Beam */}
        <div className="absolute w-[200vw] h-[200vw] md:w-[100vw] md:h-[100vw] rounded-full animate-radar-spin">
          <div className="w-1/2 h-1/2 bg-gradient-to-tr from-transparent via-primary-neon/5 to-primary-neon/20 origin-bottom-right rounded-tl-full" />
        </div>
      </div>

      {/* Floating Data Particles */}
      <div className="fixed inset-0 overflow-hidden pointer-events-none z-0">
        {[...Array(15)].map((_, i) => (
          <div 
            key={i}
            className="absolute w-1 h-1 bg-primary-neon rounded-full shadow-[0_0_5px_rgba(0,240,255,0.8)] animate-float-particle"
            style={{
              left: `${Math.random() * 100}%`,
              bottom: `-${Math.random() * 20}%`,
              animationDuration: `${10 + Math.random() * 15}s`,
              animationDelay: `${Math.random() * 5}s`,
              opacity: 0.2 + Math.random() * 0.5
            }}
          />
        ))}
        {[...Array(10)].map((_, i) => (
          <div 
            key={`m-${i}`}
            className="absolute w-1.5 h-1.5 bg-secondary-magenta rounded-full shadow-[0_0_8px_rgba(255,0,229,0.8)] animate-float-particle"
            style={{
              left: `${Math.random() * 100}%`,
              bottom: `-${Math.random() * 20}%`,
              animationDuration: `${12 + Math.random() * 18}s`,
              animationDelay: `${Math.random() * 7}s`,
              opacity: 0.1 + Math.random() * 0.4
            }}
          />
        ))}
      </div>

      {/* Data Streams (Matrix-like vertical lines) */}
      <div className="fixed inset-0 overflow-hidden pointer-events-none z-0 opacity-60">
        <div className="absolute left-[15%] top-0 w-[1px] h-32 bg-gradient-to-b from-transparent via-primary-neon to-transparent animate-data-stream" style={{ animationDuration: '4s', animationDelay: '0s' }} />
        <div className="absolute left-[35%] top-0 w-[2px] h-48 bg-gradient-to-b from-transparent via-secondary-magenta to-transparent animate-data-stream" style={{ animationDuration: '5.5s', animationDelay: '1.2s' }} />
        <div className="absolute left-[65%] top-0 w-[1px] h-24 bg-gradient-to-b from-transparent via-primary-neon to-transparent animate-data-stream" style={{ animationDuration: '3.5s', animationDelay: '2.5s' }} />
        <div className="absolute left-[85%] top-0 w-[2px] h-40 bg-gradient-to-b from-transparent via-blue-500 to-transparent animate-data-stream" style={{ animationDuration: '6s', animationDelay: '0.8s' }} />
      </div>
      
      {/* Tech Grid Overlay - Increased opacity */}
      <div className="fixed inset-0 bg-grid-pattern opacity-40 pointer-events-none mix-blend-screen z-0" />

      {/* Tech Scanning Line - Thicker and brighter */}
      <div className="fixed inset-0 pointer-events-none overflow-hidden z-0">
        <div className="w-full h-[2px] bg-primary-neon/50 shadow-[0_0_20px_rgba(0,240,255,1),0_0_40px_rgba(0,240,255,0.5)] animate-scan" />
      </div>

      {/* Vignette effect - Reduced opacity so colors show through on mobile */}
      <div className="fixed inset-0 bg-[radial-gradient(ellipse_at_center,transparent_0%,#020513_100%)] pointer-events-none opacity-60 z-0" />
    </>
  );
};
