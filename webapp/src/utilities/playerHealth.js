export const getPlayerHealthFill = (value, rotation = 0) => {
  const health = Number.isFinite(value) ? Math.max(0, Math.min(100, value)) : 100;
  const radians = rotation * Math.PI / 180;
  // The dot is a circle plus its pointed lower-left corner. Find its actual
  // vertical bounds after rotation so low HP remains visible at every heading.
  const cornerY = (Math.cos(radians) - Math.sin(radians)) / 2;
  const top = Math.min(-0.5, cornerY);
  const bottom = Math.max(0.5, cornerY);
  const boundary = bottom - health / 100 * (bottom - top);
  // The upright fill canvas spans -1..1 around the marker's centre.
  return { health, stop: (boundary + 1) * 50 };
};
