import React from 'react';
import { cn } from '@/lib/utils';

interface CapsulePillProps extends React.HTMLAttributes<HTMLSpanElement> {
  variant?: 'primary' | 'secondary' | 'tertiary';
  outline?: boolean;
}

/**
 * CapsulePill Component
 * Technical-looking tag indicator with uppercase editorial typography.
 */
export const CapsulePill = ({
  children,
  className,
  variant = 'primary',
  outline = false,
  ...props
}: CapsulePillProps) => {
  const baseStyles = "px-3 py-1 rounded-full text-xs font-editorial font-bold uppercase tracking-[0.1em] transition-all duration-300";
  
  const variantStyles = {
    primary: outline ? "border-primary text-primary border" : "bg-primary text-black",
    secondary: outline ? "border-secondary text-secondary border" : "bg-secondary text-black",
    tertiary: outline ? "border-tertiary text-tertiary border" : "bg-tertiary text-black",
  };

  return (
    <span
      className={cn(baseStyles, variantStyles[variant], className)}
      {...props}
    >
      {children}
    </span>
  );
};
