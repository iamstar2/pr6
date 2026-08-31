'use client';

import { colorForLabel, textColorForLabel } from '../lib/detectionColors';

// Only these matter for the PPE judgment this pipeline actually makes - the
// underlying YOLO model also emits Mask/NO-Mask/Safety Cone/machinery/vehicle
// (it's a general construction-site model), which would just clutter the
// overlay since this app never uses them for anything.
const RELEVANT_LABELS = new Set(['Person', 'Hardhat', 'NO-Hardhat', 'Safety Vest', 'NO-Safety Vest']);

// Draws each relevant raw YOLO detection box + label on top of an image.
// `width`/`height` must be the SAME pixel dimensions the boxes were computed
// against (rpi5's image_width/image_height) so the SVG viewBox maps 1:1 onto
// the underlying <img>, regardless of how large it's actually displayed.
export default function DetectionOverlaySvg({ detections, width, height }) {
  if (!width || !height) return null;

  const relevant = (detections || []).filter((d) => RELEVANT_LABELS.has(d.label));

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      className="absolute inset-0 w-full h-full pointer-events-none"
      preserveAspectRatio="xMidYMid meet"
    >
      {relevant.map((d, i) => {
        const [x, y, w, h] = Array.isArray(d.box) ? d.box : [0, 0, 0, 0];
        const color = colorForLabel(d.label);
        const textColor = textColorForLabel(d.label);
        const labelText = `${d.label} ${Math.round((d.confidence || 0) * 100)}%`;
        // Rough monospace-ish width estimate - good enough for a background chip,
        // doesn't need to be pixel-exact.
        const labelWidth = labelText.length * 6.5 + 8;
        const labelHeight = 15;
        const labelY = y >= labelHeight ? y - labelHeight : y;

        return (
          <g key={`${d.label}-${i}-${x}-${y}`}>
            <rect x={x} y={y} width={w} height={h} fill="none" stroke={color} strokeWidth="3" rx="4" />
            <rect x={x} y={labelY} width={labelWidth} height={labelHeight} fill={color} rx="3" />
            <text x={x + 4} y={labelY + labelHeight - 4} fontSize="11" fontWeight="600" fill={textColor}>
              {labelText}
            </text>
          </g>
        );
      })}
    </svg>
  );
}
