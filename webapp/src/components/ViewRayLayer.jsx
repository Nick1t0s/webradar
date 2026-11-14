/* eslint-disable react/prop-types */
import { useLayoutEffect, useRef } from "react";
import { getRadarPosition } from "../utilities/utilities";
import { getNearestRotation } from "../utilities/radarViewport";

const ViewRayLayer = ({ local, ray, mapData, size, color, averageLatency }) => {
  const angleRef = useRef(0);
  const angle = ray
    ? getNearestRotation(angleRef.current, -Math.atan2(ray.direction.y, ray.direction.x) * 180 / Math.PI)
    : angleRef.current;
  useLayoutEffect(() => { angleRef.current = angle; }, [angle]);
  if (!ray || !mapData || !Number.isFinite(mapData.scale) || mapData.scale <= 0 || size <= 0) return null;
  const position = getRadarPosition(mapData, local.m_position);
  const mapUnits = mapData.scale * 1024;
  const distance = Math.min(ray.distance, mapUnits * Math.SQRT2);
  const x1 = position.x * size, y1 = position.y * size;
  const length = distance / mapUnits * size;
  const transition = `transform ${averageLatency}ms linear`;
  return (
    <div className="self-view-ray">
      {/* Match the marker's position and heading interpolation, including yaw wrap. */}
      <div style={{ position: "absolute", left: 0, top: 0, transform: `translate(${x1}px, ${y1}px)`, transition }}>
        <svg className="view-ray-vector" width={size} height={size} viewBox={`0 0 ${size} ${size}`}
          role="img" aria-label="Your view ray" style={{ transform: `rotate(${angle}deg)`, transition }}>
          <line x1="0" y1="0" x2={length} y2="0" stroke="#07141e" strokeWidth="4" vectorEffect="non-scaling-stroke" />
          <line x1="0" y1="0" x2={length} y2="0" stroke={color} strokeWidth="1.5" vectorEffect="non-scaling-stroke" />
        </svg>
      </div>
    </div>
  );
};

export default ViewRayLayer;
