'use client';

export default function ErrorPage() {
  return (
    <div className="flex min-h-[50vh] flex-col items-center justify-center px-4 text-center">
      <h1 className="text-xl font-semibold text-slate-900">發生錯誤</h1>
      <p className="mt-2 text-sm text-slate-500">
        請重新整理或稍後再試。若持續發生，請聯絡管理員。
      </p>
    </div>
  );
}
