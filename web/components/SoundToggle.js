'use client';

export default function SoundToggle({ enabled, onChange }) {
  return (
    <button
      type="button"
      onClick={() => onChange(!enabled)}
      className="pill border border-glass-border bg-surface-container-high text-on-surface hover:bg-surface-container-highest transition-colors"
      aria-pressed={enabled}
      title={enabled ? '알림음 끄기' : '알림음 켜기'}
    >
      <span>{enabled ? '🔊' : '🔇'}</span>
      <span>알림음 {enabled ? 'ON' : 'OFF'}</span>
    </button>
  );
}
