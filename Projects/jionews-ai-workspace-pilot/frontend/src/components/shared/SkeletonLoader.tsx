interface SkeletonProps {
  className?: string;
}

export function Skeleton({ className = "" }: SkeletonProps) {
  return (
    <div
      className={`animate-pulse rounded-lg bg-surface-border/50 ${className}`}
    />
  );
}

export function TicketRowSkeleton() {
  return (
    <div className="flex items-center gap-4 px-4 py-3 border-b border-surface-border">
      <Skeleton className="w-12 h-5" />
      <Skeleton className="flex-1 h-5" />
      <Skeleton className="w-20 h-5" />
      <Skeleton className="w-16 h-5" />
      <Skeleton className="w-24 h-5" />
    </div>
  );
}

export function CardSkeleton() {
  return (
    <div className="card p-4 space-y-3">
      <Skeleton className="w-3/4 h-5" />
      <Skeleton className="w-full h-4" />
      <Skeleton className="w-1/2 h-4" />
    </div>
  );
}

export function AnalysisSkeleton() {
  return (
    <div className="space-y-4 p-6">
      <Skeleton className="w-48 h-6" />
      <Skeleton className="w-full h-20" />
      <Skeleton className="w-full h-16" />
      <Skeleton className="w-full h-24" />
      <Skeleton className="w-2/3 h-16" />
    </div>
  );
}
