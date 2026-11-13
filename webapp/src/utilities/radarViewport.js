export const normalizeRotation = (value) => {
  const angle = Number(value);
  return Number.isFinite(angle) ? ((angle % 360) + 360) % 360 : 0;
};

// Keep angles continuous across north instead of animating a full turn.
export const getNearestRotation = (previous, target) =>
  previous + ((normalizeRotation(target) - normalizeRotation(previous) + 540) % 360) - 180;

export const canFollowView = (settings, player) =>
  !!settings?.followView && !!player && !player.m_is_dead && Number.isFinite(player.m_eye_angle);

// Fit the entire rotated square, including its corners, inside the viewport.
// Zoom and follow operate in map coordinates before this rotation is applied.
export const getRadarTransform = (size, settings, position, localPlayer) => {
  const followView = canFollowView(settings, localPlayer);
  // Game yaw 0 faces east and 90 faces north; screen Y increases downwards.
  const rotation = normalizeRotation(followView ? localPlayer.m_eye_angle - 90 : settings?.mapRotation ?? 0);
  const radians = rotation * Math.PI / 180;
  // A fixed fit in heading-up mode avoids zoom pumping as the player turns.
  const fit = followView ? Math.SQRT1_2 : 1 / (Math.abs(Math.cos(radians)) + Math.abs(Math.sin(radians)));
  const requestedZoom = Number(settings?.zoom ?? 1);
  const zoom = Number.isFinite(requestedZoom) ? Math.min(4, Math.max(1, requestedZoom)) : 1;
  const min = size * (1 - zoom);
  // Following keeps the selected player exactly at the centre, even at edges.
  // A full-map view (no follow position) stays centred on the map as before.
  const translate = (coordinate) => position
    ? size / 2 - coordinate * size * zoom
    : Math.min(0, Math.max(min, size / 2 - coordinate * size * zoom));
  return {
    rotation, fit, zoom,
    tx: translate(position?.x ?? 0.5),
    ty: translate(position?.y ?? 0.5),
  };
};
