'use client';

import { useEffect, useState } from 'react';
import { formatRelativeKorean } from '../lib/time';
import DetectionOverlaySvg from './DetectionOverlaySvg';

// rpi5 relays the exact JPEG it just ran inference on (base64, in `image_base64`),
// plus the real `image_width`/`image_height` it decoded that image at — so the SVG
// overlay below maps bbox coordinates 1:1 onto the actual photo, no assumed
// resolution needed. This costs the ESP32 nothing extra: it already sends this same
// image to rpi5 on every person-detection (not just violations), so relaying it to
// the dashboard is free. It updates only when a detection fires (event-driven,
// debounced by the ESP32's capture cooldown) — not a continuous video stream.
const FALLBACK_WIDTH = 640;
const FALLBACK_HEIGHT = 480;

export default function LiveDetectionView({ frame, onImageClick }) {
  const [, forceTick] = useState(0);

  // Re-render periodically so the "n초 전" relative timestamp stays fresh.
  useEffect(() => {
    const id = setInterval(() => forceTick((n) => n + 1), 1000);
    return () => clearInterval(id);
  }, []);

  const hasFrame = Boolean(frame);
  const hasImage = Boolean(frame?.image_base64);
  const violation = Boolean(frame?.violation);

  const imgW = frame?.image_width || FALLBACK_WIDTH;
  const imgH = frame?.image_height || FALLBACK_HEIGHT;
  const dataUri = hasImage ? `data:image/jpeg;base64,${frame.image_base64}` : null;

  return (
    <div className="glass-card p-6 flex flex-col gap-4 h-full">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <h2 className="text-lg font-semibold text-on-surface">감지 화면</h2>
      </div>

      <div
        className="relative w-full flex-1 min-h-0 overflow-hidden rounded-lg border"
        style={{
          borderColor: 'var(--color-glass-border)',
          backgroundColor: 'var(--color-surface-container-lowest)',
        }}
      >
        {hasImage && (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={dataUri}
            alt="최근 감지 캡처"
            className="absolute inset-0 w-full h-full object-contain cursor-zoom-in"
            onClick={() =>
              onImageClick?.({ url: dataUri, detections: frame.detections, width: imgW, height: imgH })
            }
          />
        )}

        <DetectionOverlaySvg detections={frame?.detections} width={imgW} height={imgH} />

        {!hasFrame && (
          <div className="absolute inset-0 flex items-center justify-center text-label-secondary text-sm">
            수신된 감지 프레임 없음 - 대기 중...
          </div>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-x-6 gap-y-1 text-sm text-on-surface-variant">
        <span>
          기기: <span className="text-on-surface font-medium">{frame?.device_id || '-'}</span>
        </span>
        <span>
          신뢰도:{' '}
          <span className="text-on-surface font-medium">
            {hasFrame && typeof frame.confidence === 'number'
              ? `${(frame.confidence * 100).toFixed(1)}%`
              : '-'}
          </span>
        </span>
        <span>
          시각:{' '}
          <span className="text-on-surface font-medium">
            {hasFrame ? formatRelativeKorean(frame.timestamp) : '-'}
          </span>
        </span>
        <span
          className="pill"
          style={{
            backgroundColor: hasFrame
              ? violation
                ? 'var(--color-error-container)'
                : 'var(--color-success)'
              : 'var(--color-surface-container-highest)',
            color: hasFrame ? (violation ? 'var(--color-on-error-container)' : 'var(--color-on-success)') : 'var(--color-label-secondary)',
          }}
        >
          {hasFrame ? (violation ? '위반 감지' : '정상') : '대기 중'}
        </span>
      </div>
    </div>
  );
}
