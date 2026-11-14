/* eslint-disable react/prop-types */
import { getPlayerColor } from "../utilities/playerColors";
import { getPlayerIdentity } from "../utilities/viewerPerspective";

const TEAM_NAMES = { 2: "Terrorists", 3: "Counter-Terrorists" };
const moneyFormat = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });
const weaponName = name => typeof name === "string"
  ? name.replace(/^weapon_/, "").replace(/[^a-z0-9_]/gi, "") : "";
const weaponLabel = name => name.replace(/_silencer$/, "-S").replaceAll("_", " ").toUpperCase();
const isDead = player => player.m_is_dead || (Number.isFinite(player.m_health) && player.m_health <= 0);

const PortraitPlayerCard = ({ player, localTeam, settings }) => {
  const dead = isDead(player);
  const hp = dead ? 0 : Number.isFinite(player.m_health) ? Math.max(0, Math.min(100, player.m_health)) : null;
  const color = getPlayerColor(player, localTeam, settings);
  const money = Number.isFinite(player.m_money) ? `$${moneyFormat.format(player.m_money)}` : "—";
  const weapons = player.m_weapons ?? {};
  const active = weaponName(weapons.m_active);
  const inventory = [...new Set([weapons.m_primary, weapons.m_secondary, weapons.m_active].map(weaponName).filter(Boolean))];
  return (
    <li className={`portrait-player-card${dead ? " is-dead" : ""}`} data-player-id={getPlayerIdentity(player)}
      style={{ "--player-color": color }}>
      <div className="portrait-player-name">
        <span title={player.m_name}>{player.m_name || "Unnamed player"}</span>
        {player.m_is_local && <span className="portrait-player-badge">You</span>}
        {dead && <span className="portrait-player-badge">Dead</span>}
      </div>
      <div className="portrait-player-stats">
        <span className="portrait-player-hp">{hp ?? "—"} HP</span>
        <span className="portrait-player-money" title={money}>{money}</span>
      </div>
      <div className="portrait-hp-track" aria-hidden="true">
        <div style={{ width: `${hp ?? 0}%` }} />
      </div>
      <ul className="portrait-weapon-list" aria-label="Weapons">
        {inventory.map(name => (
          <li key={name} className={name === active ? "is-active" : undefined}
            title={`${weaponLabel(name)}${name === active ? " (active)" : ""}`}>
            <span className="portrait-weapon-icon" aria-hidden="true" style={{
              mask: `url('./assets/icons/${name}.svg') no-repeat center / contain`,
              WebkitMask: `url('./assets/icons/${name}.svg') no-repeat center / contain`,
            }} />
            <span>{weaponLabel(name)}</span>
          </li>
        ))}
        {inventory.length === 0 && <li>—</li>}
      </ul>
    </li>
  );
};

const PortraitTeamPanel = ({ team, players, localTeam, settings }) => {
  const roster = players.filter(player => player.m_team == team);
  const relation = localTeam === 2 || localTeam === 3 ? team === localTeam ? "Your team" : "Opponents" : "";
  const title = [relation, TEAM_NAMES[team]].filter(Boolean).join(" · ");
  return (
    <section className="portrait-team-panel" data-team={team} aria-label={title}>
      <div className="portrait-team-heading">
        <h2 title={title}>{title}</h2>
        <span>{roster.filter(player => !isDead(player)).length}/{roster.length} alive</span>
      </div>
      <ul className="portrait-player-list" aria-label={`${TEAM_NAMES[team]} players`}>
        {roster.map(player => <PortraitPlayerCard key={getPlayerIdentity(player)} player={player} localTeam={localTeam} settings={settings} />)}
        {roster.length === 0 && <li className="portrait-team-empty">No players</li>}
      </ul>
    </section>
  );
};

export default PortraitTeamPanel;
