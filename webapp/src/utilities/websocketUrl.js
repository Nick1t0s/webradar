export const getWebSocketUrl = (location, { override, useLocalhost = false } = {}) => {
  if (override) return override;
  if (useLocalhost) return "ws://localhost:22006/cs2_webradar";
  // Both Vite and the helper's HTTP server proxy this path. Preserve the page's
  // external port so HTTP users don't need to expose the internal WS port too.
  return `${location.protocol === "https:" ? "wss:" : "ws:"}//${location.host}/cs2_webradar`;
};
