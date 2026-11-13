import { useLayoutEffect, useMemo, useRef, useState } from "react";
import { getRadarTransform } from "../utilities/radarViewport";
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
  const { rotation, fit, zoom, tx, ty } = getRadarTransform(size, settings, position);

  return (
    <div ref={viewportRef} className="radar-viewport">
      <div id="radar" className="relative" style={{ width: size, height: size, flexShrink: 0 }}>
        <div className="radar-rotation" style={{ transform: `rotate(${rotation}deg) scale(${fit})` }}>
          <div className="radar-clip" style={{ overflow: zoom > 1 ? "hidden" : "visible" }}>
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
  );
};

export default Radar;

