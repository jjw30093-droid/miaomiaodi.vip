import React from 'react';
import { cn } from '@/lib/utils';

interface CyberCardProps extends React.HTMLAttributes<HTMLDivElement> {
  children: React.ReactNode;
  variant?: 'default' | 'high' | 'low';
}

/**
 * CyberCard Component
 * Implements the "Signature Glass Card" from the Synthetic Ether design system.
 * Features: blur(12px), 60% opacity, and glowing gradient border.
 */
export const CyberCard = ({ 
  children, 
  className, 
  variant = 'default',
  ...props 
}: CyberCardProps) => {
  const variantStyles = {
    default: 'bg-surface-card',
    high: 'bg-[rgba(41,44,52,0.8)]',
    low: 'bg-[rgba(17,19,25,0.4)]',
  };

  return (
    <div
      className={cn(
        "glass-cyber rounded-cyber overflow-hidden transition-all duration-500",
        variantStyles[variant],
        className
      )}
      {...props}
    >
      <div className="p-6 md:p-8 relative z-10">
        {children}
      </div>
      
      {/* Light leak effect */}
      <div className="absolute inset-0 bg-gradient-to-br from-primary/5 to-secondary/5 pointer-events-none" />
    </div>
  );
};
