import { getWebSocketUrl } from "./websocketUrl.js";

export const CONNECTION_STORAGE_KEY = "radarConnectionUrl";

/** Проверяет явно заданный адрес источника данных; пустая строка сбрасывает его. */
export const normalizeConnectionUrl = value => {
  const text = value.trim();
  if (!text) return "";
  let url;
  try {
    url = new URL(text);
  } catch {
    throw new Error("Enter a valid ws:// or wss:// data source URL.");
  }
  if (!/^wss?:$/.test(url.protocol) || !url.hostname || url.username || url.password ||
      url.hash || /\s/.test(text) || url.port === "0") {
    throw new Error("Use ws:// or wss:// with a host, without credentials, spaces or a fragment.");
  }
  return url.href;
};

/** Читает сохранённый источник, игнорируя недоступное или повреждённое хранилище. */
export const readConnectionUrl = storage => {
  try {
    return normalizeConnectionUrl(storage.getItem(CONNECTION_STORAGE_KEY) || "");
  } catch {
    return "";
  }
};

/** Возвращает рабочий адрес по умолчанию и ошибку конфигурации вместо падения UI. */
export const getDefaultConnection = (location, options) => {
  try {
    return { url: normalizeConnectionUrl(getWebSocketUrl(location, options)), error: "" };
  } catch (exception) {
    return {
      url: getWebSocketUrl(location, { useLocalhost: options.useLocalhost }),
      error: `Configured default source is invalid: ${exception instanceof Error ? exception.message : "invalid URL"}`,
    };
  }
};
