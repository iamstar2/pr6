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

function Thumbnail({ previewSrc, onClick }) {
  // `previewSrc` is the cloud image_url once saved, or falls back to the
  // base64 capture rpi5 already sent at violation time (item.image_base64) —
  // so the thumbnail (and click-to-enlarge) works even while cloud upload is
  // still pending/failed, not only after "저장 완료".
  if (previewSrc) {
    return (
      // eslint-disable-next-line @next/next/no-img-element
      <img
        src={previewSrc}
        alt="위반 캡처 썸네일"
        className="w-16 h-16 rounded-md object-cover border cursor-zoom-in"
        style={{ borderColor: 'var(--color-glass-border)' }}
        onClick={onClick}
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
      ⏳
    </div>
  );
}

const TYPE_OPTIONS = [
  { value: 'all', label: '전체 유형' },
  { value: 'no_helmet', label: '헬멧만 미착용' },
  { value: 'no_vest', label: '조끼만 미착용' },
  { value: 'both', label: '둘 다 미착용' },
];

function violationType(item) {
  if (!item.helmet_detected && !item.vest_detected) return 'both';
  if (!item.helmet_detected) return 'no_helmet';
  if (!item.vest_detected) return 'no_vest';
  return null;
}

export default function ViolationHistory({ items, onImageClick }) {
  const [, forceTick] = useState(0);
  const [deviceFilter, setDeviceFilter] = useState('all');
  const [typeFilter, setTypeFilter] = useState('all');

  useEffect(() => {
    const id = setInterval(() => forceTick((n) => n + 1), 1000);
    return () => clearInterval(id);
  }, []);

  const devices = Array.from(new Set(items.map((i) => i.device_id).filter(Boolean)));

  const filtered = items.filter((item) => {
    if (deviceFilter !== 'all' && item.device_id !== deviceFilter) return false;
    if (typeFilter !== 'all' && violationType(item) !== typeFilter) return false;
    return true;
  });

  const selectClass =
    'text-xs rounded-md border px-2 py-1 bg-surface-container-low text-on-surface';
  const selectStyle = { borderColor: 'var(--color-glass-border)' };

  return (
    <div className="glass-card p-6 flex flex-col gap-4 h-full">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <h2 className="text-lg font-semibold text-on-surface">최근 위반 이력</h2>
        <span className="text-xs text-label-secondary">
          {filtered.length} / {items.length}건
        </span>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <select
          value={deviceFilter}
          onChange={(e) => setDeviceFilter(e.target.value)}
          className={selectClass}
          style={selectStyle}
          aria-label="기기 필터"
        >
          <option value="all">전체 기기</option>
          {devices.map((d) => (
            <option key={d} value={d}>
              {d}
            </option>
          ))}
        </select>
        <select
          value={typeFilter}
          onChange={(e) => setTypeFilter(e.target.value)}
          className={selectClass}
          style={selectStyle}
          aria-label="위반 유형 필터"
        >
          {TYPE_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
      </div>

      {items.length === 0 ? (
        <p className="text-sm text-label-secondary py-8 text-center flex-1">아직 위반 이력이 없습니다.</p>
      ) : filtered.length === 0 ? (
        <p className="text-sm text-label-secondary py-8 text-center flex-1">조건에 맞는 이력이 없습니다.</p>
      ) : (
        <ul className="flex flex-col gap-3 flex-1 min-h-0 overflow-y-auto pr-1">
          {filtered.map((item) => (
            <li
              key={item.request_id}
              className="flex items-center gap-4 p-3 rounded-lg border"
              style={{ borderColor: 'var(--color-glass-border)', backgroundColor: 'var(--color-surface-container-low)' }}
            >
              <Thumbnail
                previewSrc={
                  item.image_url ||
                  (item.image_base64 ? `data:image/jpeg;base64,${item.image_base64}` : '')
                }
                onClick={() =>
                  onImageClick?.({
                    url: item.image_url || `data:image/jpeg;base64,${item.image_base64}`,
                    detections: item.detections,
                    width: item.image_width,
                    height: item.image_height,
                  })
                }
              />
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
