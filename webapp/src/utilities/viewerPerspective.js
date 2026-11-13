export const HELPER_VIEWER = "helper";

// Steam IDs survive nickname, slot and team changes. Bots have no Steam ID;
// include their name in the fallback so a reused slot won't select a stranger.
export const getPlayerIdentity = (player) => {
  const steamId = String(player.m_steam_id ?? "");
  if (/^[1-9]\d*$/.test(steamId)) return `steam:${steamId}`;
  return `slot:${player.m_idx}:${encodeURIComponent(player.m_name ?? "")}`;
};

export const getViewerPerspective = (players, viewerId, fallbackTeam) => {
  const helper = viewerId === HELPER_VIEWER;
  const selectedPlayer = helper
    ? players.find(player => player.m_is_local)
    : players.find(player => getPlayerIdentity(player) === viewerId);
  const team = selectedPlayer?.m_team;
  return {
    selectedPlayer,
    missing: !helper && !selectedPlayer,
    localTeam: team === 2 || team === 3 ? team : helper ? fallbackTeam : 0,
    // Never mutate the shared frame: each page derives its own local player.
    players: players.map(player => ({ ...player, m_is_local: player === selectedPlayer })),
  };
};
