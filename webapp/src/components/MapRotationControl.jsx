/* eslint-disable react/prop-types */
import { useId } from "react";
import { normalizeRotation } from "../utilities/radarViewport";

const MapRotationControl = ({ settings, onChange }) => {
  const id = useId();
  const angle = normalizeRotation(settings?.mapRotation ?? 0);
  return (
    <div className="map-rotation-control">
      <div className="flex justify-between items-center">
        <label htmlFor={id}>Map Rotation</label>
        <output htmlFor={id}>{angle}°</output>
      </div>
      <input
        id={id} type="range" min="0" max="359" step="1" value={angle}
        onChange={event => onChange(Number(event.target.value))}
      />
      <div className="map-rotation-buttons">
        <button type="button" aria-label="Rotate map counterclockwise by 90 degrees"
          onClick={() => onChange(normalizeRotation(angle - 90))}>↶ 90°</button>
        <button type="button" aria-label="Reset map rotation"
          onClick={() => onChange(0)}>Reset</button>
        <button type="button" aria-label="Rotate map clockwise by 90 degrees"
          onClick={() => onChange(normalizeRotation(angle + 90))}>↷ 90°</button>
      </div>
    </div>
  );
};

export default MapRotationControl;
