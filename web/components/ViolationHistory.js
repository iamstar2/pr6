'use client';

import { useEffect, useState } from 'react';
import { formatRelativeKorean } from '../lib/time';

function StatusBadge({ status }) {
  const map = {
    pending: { label: '저장 중', bg: 'var(--color-warning)', fg: 'var(--color-on-warning)' },
    success: { label: '저장 완료', bg: 'var(--color-success)', fg: 'var(--color-on-success)' },
    failed: { label: '저장 실패', bg: 'var(--color-error)', fg: 'var(--color-on-error)' },
  };
  const s = map[status] || map.pending;
  return (
    <span className="pill" style={{ backgroundColor: s.bg, color: s.fg }}>
      {s.label}
    </span>
  );
}

function Thumbnail({ status, imageUrl }) {
  if (status === 'success' && imageUrl) {
    return (
      // eslint-disable-next-line @next/next/no-img-element
      <img
        src={imageUrl}
        alt="위반 캡처 썸네일"
        className="w-16 h-16 rounded-md object-cover border"
        style={{ borderColor: 'var(--color-glass-border)' }}
        onError={(e) => {
          e.currentTarget.style.display = 'none';
        }}
      />
    );
  }
  return (
    <div
      className="w-16 h-16 rounded-md border flex items-center justify-center text-xl"
      style={{
        borderColor: 'var(--color-glass-border)',
        backgroundColor: 'var(--color-surface-container-highest)',
        color: 'var(--color-label-secondary)',
      }}
      aria-label="썸네일 없음"
    >
      {status === 'failed' ? '⚠️' : '⏳'}
    </div>
  );
}

export default function ViolationHistory({ items }) {
  const [, forceTick] = useState(0);

  useEffect(() => {
    const id = setInterval(() => forceTick((n) => n + 1), 1000);
    return () => clearInterval(id);
  }, []);

  return (
    <div className="glass-card p-6 flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-on-surface">최근 위반 이력</h2>
        <span className="text-xs text-label-secondary">{items.length}건</span>
      </div>

      {items.length === 0 ? (
        <p className="text-sm text-label-secondary py-8 text-center">아직 위반 이력이 없습니다.</p>
      ) : (
        <ul className="flex flex-col gap-3 max-h-[560px] overflow-y-auto pr-1">
          {items.map((item) => (
            <li
              key={item.request_id}
              className="flex items-center gap-4 p-3 rounded-lg border"
              style={{ borderColor: 'var(--color-glass-border)', backgroundColor: 'var(--color-surface-container-low)' }}
            >
              <Thumbnail status={item.cloudStatus} imageUrl={item.image_url} />
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="font-medium text-on-surface truncate">{item.device_id || '알 수 없는 기기'}</span>
                  <StatusBadge status={item.cloudStatus} />
                </div>
                <p className="text-xs text-label-secondary mt-1">
                  {formatRelativeKorean(item.timestamp)} · 신뢰도{' '}
                  {typeof item.confidence === 'number' ? `${(item.confidence * 100).toFixed(0)}%` : '-'}
                </p>
                <p className="text-xs text-label-secondary mt-0.5">
                  헬멧 {item.helmet_detected ? '✔' : '✘'} · 조끼 {item.vest_detected ? '✔' : '✘'}
                </p>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
