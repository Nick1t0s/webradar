/* eslint-disable react/prop-types */
import { getPlayerHealthFill } from "../utilities/playerHealth";

const PlayerHealthFill = ({ health, color, playerRotation, mapRotation, averageLatency }) => {
  const fill = getPlayerHealthFill(health, mapRotation + playerRotation + 315);
  return (
    <div className="player-health-fill absolute inset-0" role="img" aria-label={`${fill.health} HP`}
      title={`${fill.health} HP`} data-health={fill.health} style={{ transform: "rotate(-315deg)" }}>
      {/* Cancel each animated rotation separately, keeping the white part on
          screen-top while the dot retains its original heading and shape. */}
      <div className="absolute inset-0" style={{ transform: `rotate(${-playerRotation}deg)`, transition: `transform ${averageLatency}ms linear` }}>
        <div className="radar-upright absolute inset-0">
          <div className="player-health-level" style={{
            backgroundColor: fill.health === 0 ? "#fff" : color,
            backgroundImage: fill.health === 0 || fill.health === 100 ? "none"
              : `linear-gradient(to bottom, #fff ${fill.stop}%, ${color} ${fill.stop}%)`,
          }} />
        </div>
      </div>
    </div>
  );
};

export default PlayerHealthFill;
