// Formats a timestamp as a relative Korean "n초 전 / n분 전 / n시간 전" string.
export function formatRelativeKorean(isoString, nowMs = Date.now()) {
  if (!isoString) return '-';
  const then = new Date(isoString).getTime();
  if (Number.isNaN(then)) return '-';

  const diffSec = Math.max(0, Math.floor((nowMs - then) / 1000));

  if (diffSec < 60) return `${diffSec}초 전`;
  const diffMin = Math.floor(diffSec / 60);
  if (diffMin < 60) return `${diffMin}분 전`;
  const diffHour = Math.floor(diffMin / 60);
  if (diffHour < 24) return `${diffHour}시간 전`;
  const diffDay = Math.floor(diffHour / 24);
  return `${diffDay}일 전`;
}
