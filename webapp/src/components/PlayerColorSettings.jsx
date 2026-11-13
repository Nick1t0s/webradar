/* eslint-disable react/prop-types */
import ColorField from "./ColorField";
import { PLAYER_COLOR_OPTIONS } from "../utilities/playerColors";

const PRESETS = ["#4ade80", "#ef4444", "#00cfff", "#ffdd00", "#ff3df0", "#ffffff"];

const PlayerColorSettings = ({ settings, onChange }) => (
  <div>
    {PLAYER_COLOR_OPTIONS.map(({ key, label, defaultColor }) => {
      const color = settings[key] ?? defaultColor;
      return (
        <fieldset key={key} style={{ margin: "10px 0", minWidth: 0 }}>
          <legend style={{ color: "#8ab", fontSize: 12, marginBottom: 6 }}>{label}</legend>
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center" }}>
            {PRESETS.map(preset => (
              <button key={preset} type="button" title={preset}
                aria-label={`${label}: ${preset}`} aria-pressed={color.toLowerCase() === preset}
                onClick={() => onChange(key, preset)}
                style={{ width: 20, height: 20, borderRadius: "50%", background: preset,
                  cursor: "pointer", flexShrink: 0,
                  border: color.toLowerCase() === preset ? "2px solid #fff" : "2px solid rgba(255,255,255,0.25)" }} />
            ))}
            <ColorField value={color} onChange={value => onChange(key, value)} />
          </div>
        </fieldset>
      );
    })}
  </div>
);

export default PlayerColorSettings;
