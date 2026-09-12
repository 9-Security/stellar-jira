import Link from 'next/link';
import { Button } from './ui/button';

export function EmptyState({
  title,
  description,
  actionHref,
  actionLabel,
}: {
  title: string;
  description: string;
  actionHref?: string;
  actionLabel?: string;
}) {
  return (
    <div className="flex flex-col items-center justify-center rounded-2xl border border-dashed border-slate-200 bg-white px-6 py-16 text-center">
      <p className="text-base font-semibold text-slate-900">{title}</p>
      <p className="mt-1 max-w-md text-sm text-slate-500">{description}</p>
      {actionHref && actionLabel ? (
        <Link href={actionHref} className="mt-5">
          <Button>{actionLabel}</Button>
        </Link>
      ) : null}
    </div>
  );
}
