/* eslint-disable react/prop-types */
import { useId } from "react";
import { normalizeRotation } from "../utilities/radarViewport";

const MapRotationControl = ({ settings, onChange, onFollowViewChange }) => {
  const id = useId();
  const angle = normalizeRotation(settings?.mapRotation ?? 0);
  const followView = !!settings?.followView;
  return (
    <div className="map-rotation-control">
      <button type="button" role="switch" aria-checked={followView}
        aria-label="Rotate with view" className="map-follow-view"
        onClick={() => onFollowViewChange(!followView)}>
        <span>Rotate with view</span>
        <span style={{ color: followView ? "#4ade80" : "#8ab" }}>{followView ? "On" : "Off"}</span>
      </button>
      {followView && <p className="map-follow-view-hint">Your view faces up. Labels stay upright.</p>}
      <div className="flex justify-between items-center">
        <label htmlFor={id}>Map Rotation</label>
        <output htmlFor={id}>{angle}°</output>
      </div>
      <input
        id={id} type="range" min="0" max="359" step="1" value={angle} disabled={followView}
        onChange={event => onChange(Number(event.target.value))}
      />
      <div className="map-rotation-buttons">
        <button type="button" disabled={followView} aria-label="Rotate map counterclockwise by 90 degrees"
          onClick={() => onChange(normalizeRotation(angle - 90))}>↶ 90°</button>
        <button type="button" disabled={followView} aria-label="Reset map rotation"
          onClick={() => onChange(0)}>Reset</button>
        <button type="button" disabled={followView} aria-label="Rotate map clockwise by 90 degrees"
          onClick={() => onChange(normalizeRotation(angle + 90))}>↷ 90°</button>
      </div>
    </div>
  );
};

export default MapRotationControl;
