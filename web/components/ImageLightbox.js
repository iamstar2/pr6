'use client';

import { useEffect } from 'react';
import DetectionOverlaySvg from './DetectionOverlaySvg';

// Full-size overlay for viewing a thumbnail/live-frame image bigger, with the
// same labeled YOLO box overlay as the live view. Closes on backdrop click or
// Escape. `data.url` can be a data: URI (live frame) or a real image_url
// (cloud-stored violation photo) - both just work as <img src>.
export default function ImageLightbox({ data, onClose }) {
  const url = data?.url;

  useEffect(() => {
    if (!url) return undefined;
    const onKey = (e) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [url, onClose]);

  if (!url) return null;

  const hasBoxSize = Boolean(data.width && data.height);

  return (
    <div
      role="dialog"
      aria-modal="true"
      className="fixed inset-0 z-50 flex items-center justify-center p-6"
      style={{ backgroundColor: 'rgba(0, 0, 0, 0.8)' }}
      onClick={onClose}
    >
      {/* inline-block so this wrapper's size comes from the <img>'s own rendered
          box (normal flow, not absolutely positioned) - the overlay SVG then sits
          on top at exactly that size. An absolutely-positioned <img> here would
          take it out of flow and leave the wrapper with nothing to size itself
          against, collapsing to 0x0 and making the whole lightbox invisible. */}
      <div className="relative inline-block max-w-full max-h-full" onClick={(e) => e.stopPropagation()}>
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={url}
          alt="확대 이미지"
          className="block max-w-[90vw] max-h-[90vh] w-auto h-auto rounded-lg object-contain"
        />
        {hasBoxSize && (
          <DetectionOverlaySvg detections={data.detections} width={data.width} height={data.height} />
        )}
      </div>

      <div className="absolute top-4 right-4 flex items-center gap-2">
        {/* `download` is honored reliably for the data: URIs (live frame captures);
            for cross-origin image_url (Supabase), the browser only honors it when
            the host's CORS headers allow it - otherwise this just opens the image
            in a new tab, which still lets the user save it via right-click. */}
        <a
          href={url}
          download={`violation-${Date.now()}.jpg`}
          target="_blank"
          rel="noreferrer"
          onClick={(e) => e.stopPropagation()}
          className="pill"
          style={{ backgroundColor: 'var(--color-primary)', color: 'var(--color-on-primary)' }}
        >
          ⬇ 다운로드
        </a>
        <button
          type="button"
          onClick={onClose}
          aria-label="닫기"
          className="pill"
          style={{ backgroundColor: 'var(--color-surface-container-highest)', color: 'var(--color-on-surface)' }}
        >
          ✕ 닫기
        </button>
      </div>
    </div>
  );
}
