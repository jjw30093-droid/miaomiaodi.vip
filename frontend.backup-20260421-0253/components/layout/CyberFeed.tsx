import React from 'react';
import { cn } from '@/lib/utils';

interface CyberFeedProps extends React.HTMLAttributes<HTMLDivElement> {
  children: React.ReactNode;
}

/**
 * CyberFeed Component
 * Implements "Intentional Asymmetry" layout.
 * Features staggered animation and breathing room.
 */
export const CyberFeed = ({ children, className, ...props }: CyberFeedProps) => {
  return (
    <div
      className={cn(
        "grid gap-12 sm:gap-20 max-w-7xl mx-auto py-12 md:py-24 px-6 md:px-12",
        className
      )}
      {...props}
    >
      <div className="flex flex-col gap-16 md:gap-24 animate-slide-up">
        {React.Children.map(children, (child, index) => (
          <div
            key={index}
            className={cn(
              "w-full max-w-3xl",
              index % 2 === 0 ? "self-start" : "self-end",
              "transition-all duration-700 delay-[200ms]"
            )}
            style={{ 
              animationDelay: `${index * 150}ms`,
              marginTop: index > 0 ? (index % 3 === 0 ? '4rem' : '0') : '0' 
            }}
          >
            {child}
          </div>
        ))}
      </div>
    </div>
  );
};
