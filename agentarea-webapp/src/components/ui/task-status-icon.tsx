
import { Check, CircleDashed, X, Circle } from 'lucide-react';
import { TaskWithAgent } from '@/lib/api';
import { cn } from '@/lib/utils';

type TaskStatusIconProps = {
  status: TaskWithAgent['status'];
  className?: string;
};

export const TaskStatusIcon = ({ status, className }: TaskStatusIconProps) => {
  switch (status) {
    case 'completed':
    case 'success':
      return (
        <div className={cn('flex items-center justify-center rounded-full bg-green-500/40 dark:bg-green-700/50', className)}>
          <Check className="h-3/4 w-3/4 text-green-500/80" strokeWidth={3} />
        </div>
      );
    case 'failed':
    case 'error':
      return (
        <div className={cn('flex items-center justify-center rounded-full bg-destructive/40 dark:bg-red-400/50', className)}>
          <X className="h-3/4 w-3/4 text-destructive/80 dark:text-destructive" strokeWidth={3} />
        </div>
      );
    case 'in_progress':
    case 'running':
      return (
        <CircleDashed
          className={cn('text-primary/70 dark:text-primary/60', className)}
          strokeWidth={2.5}
        />
      );
    case 'pending':
    case 'paused':
    default:
      return (
        <Circle
          className={cn('text-muted-foreground/30 dark:text-muted-foreground/20', className)}
          strokeWidth={3}
        />
      );
  }
};
