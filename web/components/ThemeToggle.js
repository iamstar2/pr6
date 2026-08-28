'use client';

import { useEffect, useState } from 'react';

export default function ThemeToggle() {
  const [theme, setTheme] = useState('light');

  useEffect(() => {
    const current = document.documentElement.getAttribute('data-theme') || 'light';
    setTheme(current);
  }, []);

  function toggleTheme() {
    const next = theme === 'dark' ? 'light' : 'dark';
    setTheme(next);
    document.documentElement.setAttribute('data-theme', next);
    try {
      window.localStorage.setItem('theme', next);
    } catch (e) {
      // localStorage unavailable (private mode etc.) - theme just won't persist.
    }
  }

  return (
    <button
      type="button"
      onClick={toggleTheme}
      className="pill border border-glass-border bg-surface-container-high text-on-surface hover:bg-surface-container-highest transition-colors"
      aria-label="테마 전환"
      title={theme === 'dark' ? '라이트 테마로 전환' : '다크 테마로 전환'}
    >
      <span>{theme === 'dark' ? '🌙' : '☀️'}</span>
      <span>{theme === 'dark' ? '다크' : '라이트'}</span>
    </button>
  );
}
