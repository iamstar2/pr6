import { Inter } from 'next/font/google';
import './globals.css';

// next/font self-hosts the font at build time (no runtime request to Google, no
// flash-of-fallback) — this is what actually makes the DESIGN.md-specified Inter
// typeface render, instead of silently falling back to the OS default font.
const inter = Inter({ subsets: ['latin'], weight: ['400', '500', '600', '700'], variable: '--font-inter' });

export const metadata = {
  title: '안전 위반 모니터링 대시보드',
  description: 'ESP32/RPi5 PPE 감지 파이프라인 실시간 모니터링 대시보드',
};

// Runs before paint (blocking, in <head>) to avoid a dark-theme flash: reads
// the persisted theme preference and stamps data-theme on <html> right away.
// Defaults to "light" when nothing is stored yet.
const THEME_INIT_SCRIPT = `
(function () {
  try {
    var stored = window.localStorage.getItem('theme');
    var theme = stored === 'light' || stored === 'dark' ? stored : 'light';
    document.documentElement.setAttribute('data-theme', theme);
  } catch (e) {
    document.documentElement.setAttribute('data-theme', 'light');
  }
})();
`;

export default function RootLayout({ children }) {
  return (
    <html lang="ko" className={inter.variable}>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_INIT_SCRIPT }} />
      </head>
      <body>{children}</body>
    </html>
  );
}
