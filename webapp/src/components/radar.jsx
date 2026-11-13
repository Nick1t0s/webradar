import { useLayoutEffect, useMemo, useRef, useState } from "react";
import { canFollowView, getNearestRotation, getRadarTransform } from "../utilities/radarViewport";
import { getRadarPosition, getHeightRelation, isLowerLevel } from "../utilities/utilities";
import Player from "./player";
import Bomb from "./bomb";
import GrenadeLayer from "./GrenadeLayer";
import CalloutLayer from "./CalloutLayer";
import DroppedItemLayer from "./DroppedItemLayer";

const Radar = ({
  playerArray,
  radarImage,
  mapData,
  localTeam,
  averageLatency,
  bombData,
  grenades,
  dropped,
  settings
}) => {
  const viewportRef = useRef(null);
  const [size, setSize] = useState(0);
  const rotationRef = useRef(0);

  useLayoutEffect(() => {
    const viewport = viewportRef.current;
    const measure = () => setSize(Math.max(0, Math.min(viewport.clientWidth, viewport.clientHeight)));
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(viewport);
    return () => observer.disconnect();
  }, []);

  // All layers use the same untransformed dimensions. Resizing updates them
  // even when the helper isn't sending frames.
  const radarImageEl = useMemo(() => ({
    offsetWidth: size,
    offsetHeight: size,
    getBoundingClientRect: () => ({ width: size, height: size }),
  }), [size]);

  // Show the level the local player is on; players above / below you get a ▲/▼ marker (see Player).
  const local = playerArray.find((p) => p.m_is_local);
  const lower = isLowerLevel(mapData, local?.m_position?.z);
  const radarSrc = lower ? radarImage.replace(/radar\.png$/, "radar_lower.png") : radarImage;

  const me = settings?.followMe ? playerArray.find((p) => p.m_is_local && !p.m_is_dead) : null;
  const position = me && mapData ? getRadarPosition(mapData, me.m_position) : null;
  const { rotation: targetRotation, fit, zoom, tx, ty } = getRadarTransform(size, settings, position, local);
  const rotation = getNearestRotation(rotationRef.current, targetRotation);
  const followView = canFollowView(settings, local);
  useLayoutEffect(() => { rotationRef.current = rotation; }, [rotation]);

  return (
    <div ref={viewportRef} className="radar-viewport">
      <div id="radar" className="relative" style={{ width: size, height: size, flexShrink: 0,
        "--radar-counter-rotation": `${-rotation}deg`,
        "--radar-motion": followView ? `transform ${averageLatency}ms linear` : "none",
      }}>
        <div className="radar-fit" style={{ transform: `scale(${fit})` }}>
          <div className="radar-rotation" style={{ transform: `rotate(${rotation}deg)` }}>
            <div className="radar-clip" style={{ overflow: zoom > 1 || position ? "hidden" : "visible" }}>
              <div className="radar-content" style={{ transform: `translate(${tx}px, ${ty}px) scale(${zoom})` }}>
                <img className="w-full h-full" src={radarSrc} alt={`${mapData?.name ?? "Map"} radar`} />

                <CalloutLayer
                  mapName={mapData?.name}
                  radarImage={radarImageEl}
                  enabled={settings?.showCallouts ?? true}
                />

                {playerArray.map((player) => (
                  <Player
                    key={player.m_idx}
                    playerData={player}
                    mapData={mapData}
                    radarImage={radarImageEl}
                    localTeam={localTeam}
                    averageLatency={averageLatency}
                    settings={settings}
                    heightMarker={getHeightRelation(mapData, player, local, settings?.heightMarkerThreshold ?? 48)}
                  />
                ))}

                {bombData && bombData.x !== undefined && (
                  <Bomb
                    bombData={bombData}
                    mapData={mapData}
                    radarImage={radarImageEl}
                    localTeam={localTeam}
                    averageLatency={averageLatency}
                    settings={settings}
                  />
                )}

                <GrenadeLayer
                  grenades={grenades}
                  mapData={mapData}
                  radarImage={radarImageEl}
                  settings={settings}
                />

                <DroppedItemLayer
                  items={dropped}
                  mapData={mapData}
                  radarImage={radarImageEl}
                  settings={settings}
                />
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default Radar;

