import type { Metadata } from 'next';
import { DM_Sans } from 'next/font/google';
import { Suspense } from 'react';
import { Providers } from '@/components/providers';
import './globals.css';

const sans = DM_Sans({
  subsets: ['latin'],
  variable: '--font-sans',
});

export const metadata: Metadata = {
  title: 'Nine CRM',
  description: '雲端多租戶 SaaS CRM',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-Hant">
      <body className={`${sans.variable} font-sans antialiased`}>
        <Providers>
          <Suspense fallback={null}>{children}</Suspense>
        </Providers>
      </body>
    </html>
  );
}
