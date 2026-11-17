/* eslint-disable react/prop-types */
import { useId, useState } from "react";

/** Настраивает адрес helper одинаково для обычного радара и миникарты. */
const ConnectionSettings = ({ connection }) => {
  const id = useId();
  const [draft, setDraft] = useState(connection.override);
  const [error, setError] = useState("");
  const apply = value => {
    try {
      connection.setSource(value);
      setDraft(value);
      setError("");
    } catch (exception) {
      setError(exception instanceof Error ? exception.message : "Invalid data source URL.");
    }
  };
  return (
    <section style={{ marginBottom: 12, color: "#b1d0e7", fontSize: 12 }}>
      <label htmlFor={id} style={{ display: "block", fontWeight: 600, marginBottom: 5 }}>Data source (WebSocket)</label>
      <input id={id} type="text" value={draft} placeholder={connection.defaultUrl}
        spellCheck={false} autoComplete="off"
        onChange={event => setDraft(event.target.value)}
        style={{ width: "100%", boxSizing: "border-box", padding: 6, background: "#102331", color: "#fff", border: "1px solid #456", borderRadius: 4 }} />
      <div style={{ display: "flex", gap: 8, marginTop: 6 }}>
        <button type="button" onClick={() => apply(draft)}>Connect</button>
        <button type="button" onClick={() => apply("")}>Use default</button>
      </div>
      <p style={{ overflowWrap: "anywhere", margin: "6px 0" }}>Current source: {connection.url}</p>
      <p style={{ color: "#8ab", margin: "4px 0" }}>Use the helper address. Its hostname must match this site (helper access protection); the port can differ. Saved for this browser, shared by player profiles.</p>
      {!connection.override && connection.defaultError && <p role="alert" style={{ color: "#f88" }}>{connection.defaultError}</p>}
      {error && <p role="alert" style={{ color: "#f88" }}>{error}</p>}
    </section>
  );
};

export default ConnectionSettings;
