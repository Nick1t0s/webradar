/* eslint-disable react/prop-types */
import { useId } from "react";
import { getPlayerIdentity, HELPER_VIEWER } from "../utilities/viewerPerspective";

const ViewerSelector = ({ viewer }) => {
  const labelId = useId();
  const choices = [...new Map(viewer.players.map(player => [getPlayerIdentity(player), player])).entries()];
  const missing = viewer.id !== HELPER_VIEWER && !choices.some(([id]) => id === viewer.id);
  return (
    <div className="viewer-selector">
      <label htmlFor={labelId}>Your Player</label>
      <select id={labelId} value={viewer.id} onChange={event => viewer.onChange(event.target.value)}>
        <option value={HELPER_VIEWER}>Helper player (automatic)</option>
        {missing && <option value={viewer.id}>Selected player — waiting for game data</option>}
        {choices.map(([id, player]) => (
          <option key={id} value={id}>
            {player.m_name || "Unnamed player"} · {player.m_team === 2 ? "T" : player.m_team === 3 ? "CT" : "Spectator"}
            {id.startsWith("steam:") ? ` · …${id.slice(-4)}` : ` · slot ${player.m_idx}`}
            {player.m_is_dead ? " (dead)" : ""}
          </option>
        ))}
      </select>
      <p>Your player and display settings are saved for you. Other viewers keep their own view.</p>
      {missing && <p role="status">Your selected player is not in the current match. Waiting for them to return.</p>}
    </div>
  );
};

export default ViewerSelector;
