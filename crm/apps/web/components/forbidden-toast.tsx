'use client';

import { useEffect } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { toast } from 'sonner';

export function ForbiddenToast() {
  const params = useSearchParams();
  const router = useRouter();
  useEffect(() => {
    if (params.get('error') === 'forbidden') {
      toast.error('沒有權限');
      const url = new URL(window.location.href);
      url.searchParams.delete('error');
      router.replace(url.pathname + url.search);
    }
  }, [params, router]);
  return null;
}
