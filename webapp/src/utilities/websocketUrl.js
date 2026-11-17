/** Возвращает явный адрес источника или отдельный WS-порт хоста сайта. */
export const getWebSocketUrl = (location, { override, useLocalhost = false } = {}) => {
  if (override) {
    let endpoint;
    try {
      endpoint = new URL(override);
    } catch {
      throw new Error("Укажите полный адрес WebSocket: ws://host:22006/cs2_webradar");
    }
    if (!["ws:", "wss:"].includes(endpoint.protocol) || !endpoint.hostname ||
        endpoint.username || endpoint.password || endpoint.hash) {
      throw new Error("Нужен адрес ws:// или wss:// без пароля и фрагмента");
    }
    return endpoint.href;
  }
  if (useLocalhost) return "ws://localhost:22006/cs2_webradar";
  // The HTTP port only serves the site; game data comes directly from the helper.
  return `${location.protocol === "https:" ? "wss:" : "ws:"}//${location.hostname}:22006/cs2_webradar`;
};
