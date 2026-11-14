// A deliberately 2D projection, independent of map rotation, zoom and Z.
// This radius is a small aiming tolerance in world units, not a game hit test.
export const VIEW_RAY_TARGET_RADIUS = 24;
const validPosition = player => Number.isFinite(player?.m_position?.x) && Number.isFinite(player?.m_position?.y);

export const getViewRay = (local, players, { showAllies = true, localTeam = local?.m_team } = {}) => {
  if (!local || local.m_is_dead || local.m_health <= 0 || !validPosition(local) || !Number.isFinite(local.m_eye_angle)) return null;
  const radians = local.m_eye_angle * Math.PI / 180;
  const direction = { x: Math.cos(radians), y: Math.sin(radians) };
  let target = null;
  let distance = Infinity;
  for (const player of players) {
    if (player === local || player.m_is_local || player.m_is_dead || player.m_health <= 0 || !validPosition(player)) continue;
    if (!showAllies && player.m_team == localTeam) continue;
    const x = player.m_position.x - local.m_position.x;
    const y = player.m_position.y - local.m_position.y;
    const along = x * direction.x + y * direction.y;
    const across = x * direction.y - y * direction.x;
    if (along <= 0 || Math.abs(across) > VIEW_RAY_TARGET_RADIUS) continue;
    const entry = Math.max(0, along - Math.sqrt(Math.max(0, VIEW_RAY_TARGET_RADIUS ** 2 - across ** 2)));
    if (entry < distance) {
      target = player;
      distance = entry;
    }
  }
  return { direction, target, distance };
};
