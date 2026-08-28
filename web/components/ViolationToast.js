'use client';

import { useEffect } from 'react';

const AUTO_DISMISS_MS = 6000;

export default function ViolationToast({ toast, onDismiss }) {
  useEffect(() => {
    if (!toast) return undefined;
    const id = setTimeout(() => onDismiss(toast.key), AUTO_DISMISS_MS);
    return () => clearTimeout(id);
  }, [toast, onDismiss]);

  if (!toast) return null;

  return (
    <div
      role="alert"
      className="fixed top-20 right-4 z-50 w-[min(360px,calc(100vw-2rem))] rounded-xl border shadow-2xl p-4 flex gap-3 items-start"
      style={{
        backgroundColor: 'var(--color-error-container)',
        borderColor: 'var(--color-glass-border)',
        color: 'var(--color-on-error-container)',
      }}
    >
      <span className="text-2xl leading-none">⚠️</span>
      <div className="flex-1 min-w-0">
        <p className="font-semibold">위반 알림</p>
        <p className="text-sm opacity-90 mt-0.5">
          {toast.device_id || '알 수 없는 기기'}에서 안전 장비 미착용이 감지되었습니다.
        </p>
        <p className="text-xs opacity-75 mt-1">
          헬멧: {toast.helmet_detected ? '착용' : '미착용'} · 조끼: {toast.vest_detected ? '착용' : '미착용'}
        </p>
      </div>
      <button
        type="button"
        onClick={() => onDismiss(toast.key)}
        className="text-lg leading-none opacity-70 hover:opacity-100"
        aria-label="알림 닫기"
      >
        ×
      </button>
    </div>
  );
}
