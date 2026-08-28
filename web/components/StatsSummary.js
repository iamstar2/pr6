'use client';

import { isSameLocalDay } from '../lib/time';

// `items` is the violation history (only violation:true events are pushed there
// by app/page.js) — capped at 50 and reset on page refresh (no backend persistence
// in this module), so these are session-scoped stats, not a historical DB query.
export default function StatsSummary({ items, totalDetections }) {
  const today = items.filter((i) => isSameLocalDay(i.timestamp));

  let noHelmetOnly = 0;
  let noVestOnly = 0;
  let both = 0;
  let success = 0;
  let failed = 0;

  items.forEach((i) => {
    if (!i.helmet_detected && !i.vest_detected) both += 1;
    else if (!i.helmet_detected) noHelmetOnly += 1;
    else if (!i.vest_detected) noVestOnly += 1;

    if (i.cloudStatus === 'success') success += 1;
    else if (i.cloudStatus === 'failed') failed += 1;
  });

  return (
    <div className="glass-card px-6 py-3 flex flex-wrap items-center gap-x-5 gap-y-1.5 text-sm text-on-surface-variant">
      <span className="font-semibold text-on-surface">통계 (이번 세션)</span>
      <span>감지 시도 <b className="text-on-surface">{totalDetections}</b></span>
      <span>오늘 위반 <b style={{ color: 'var(--color-error)' }}>{today.length}</b></span>
      <span>누적 위반 <b className="text-on-surface">{items.length}</b></span>
      <span>헬멧만 <b className="text-on-surface">{noHelmetOnly}</b> · 조끼만 <b className="text-on-surface">{noVestOnly}</b> · 둘다 <b className="text-on-surface">{both}</b></span>
      <span>저장 완료 <b style={{ color: 'var(--color-success)' }}>{success}</b> · 실패 <b style={{ color: 'var(--color-error)' }}>{failed}</b></span>
    </div>
  );
}
