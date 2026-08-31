// Color coding for raw YOLO detection labels, shared by the live overlay and
// the lightbox overlay so both look consistent.
export function colorForLabel(label) {
  if (label === 'Person') return 'var(--color-primary)';
  if (label === 'Hardhat' || label === 'Safety Vest') return 'var(--color-success)';
  if (label === 'NO-Hardhat' || label === 'NO-Safety Vest') return 'var(--color-error)';
  return 'var(--color-outline)'; // Mask, Safety Cone, machinery, vehicle, etc. - not used for judging, shown neutrally
}

// Matching "on-*" token so label text stays readable against colorForLabel()'s
// background in both themes (the raw colors swap light/dark roles between
// themes, so a single hardcoded black/white text color isn't reliably legible).
export function textColorForLabel(label) {
  if (label === 'Person') return 'var(--color-on-primary)';
  if (label === 'Hardhat' || label === 'Safety Vest') return 'var(--color-on-success)';
  if (label === 'NO-Hardhat' || label === 'NO-Safety Vest') return 'var(--color-on-error)';
  return 'var(--color-surface)';
}
