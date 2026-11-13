export const PLAYER_COLOR_OPTIONS = [
  { key: "selfColor", label: "Self Color", defaultColor: "#4ade80" },
  { key: "teammateColor", label: "Teammate Color", defaultColor: "#4ade80" },
  { key: "enemyColor", label: "Enemy Color", defaultColor: "#ef4444" },
];

export const PLAYER_COLOR_DEFAULTS = Object.fromEntries(
  PLAYER_COLOR_OPTIONS.map(({ key, defaultColor }) => [key, defaultColor])
);

export const getPlayerColor = (player, localTeam, settings = {}) => {
  const key = player.m_is_local ? "selfColor"
    : player.m_team == localTeam ? "teammateColor" : "enemyColor";
  return settings[key] ?? PLAYER_COLOR_DEFAULTS[key];
};
