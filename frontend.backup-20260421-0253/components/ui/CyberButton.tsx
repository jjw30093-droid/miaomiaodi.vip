import React from 'react';
import { cn } from '@/lib/utils';

interface CyberButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'glass';
  size?: 'sm' | 'md' | 'lg';
}

/**
 * CyberButton Component
 * Features:
 * - Primary: Solid primary_container background, high-contrast text.
 * - Glass: Transparent, blur(8px), secondary ghost border.
 */
export const CyberButton = ({
  className,
  variant = 'primary',
  size = 'md',
  ...props
}: CyberButtonProps) => {
  const baseStyles = "inline-flex items-center justify-center rounded-full font-editorial font-bold uppercase transition-all duration-300 active:scale-95 focus:outline-none";
  
  const variantStyles = {
    primary: "bg-primary text-black hover:glow-primary hover:scale-[1.02]",
    glass: "glass-cyber bg-transparent border-secondary text-secondary hover:bg-secondary/10",
  };

  const sizeStyles = {
    sm: "px-4 py-1.5 text-xs tracking-wider",
    md: "px-6 py-2.5 text-sm tracking-widest",
    lg: "px-8 py-3.5 text-base tracking-[0.15em]",
  };

  return (
    <button
      className={cn(baseStyles, variantStyles[variant], sizeStyles[size], className)}
      {...props}
    />
  );
};
