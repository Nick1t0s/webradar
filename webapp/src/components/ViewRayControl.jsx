/* eslint-disable react/prop-types */
const ViewRayControl = ({ settings, onChange }) => {
  const enabled = !!settings.showSelfViewRay;
  return (
    <div className="view-ray-control">
      <button type="button" role="switch" aria-label="My View Ray" aria-checked={enabled}
        className="map-follow-view" onClick={() => onChange(!enabled)}>
        <span>My View Ray</span>
        <span style={{ color: enabled ? "#4ade80" : "#8ab" }}>{enabled ? "On" : "Off"}</span>
      </button>
      <p>Outline the first visible player along your view. Height and walls are ignored.</p>
    </div>
  );
};

export default ViewRayControl;
