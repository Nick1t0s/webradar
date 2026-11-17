import { useState } from "react";
import { CONNECTION_STORAGE_KEY, normalizeConnectionUrl, readConnectionUrl } from "../utilities/connectionPreferences";

/** Хранит источник данных отдельно от личных настроек выбранного игрока. */
export const useConnectionPreferences = ({ url: defaultUrl, error: defaultError }) => {
  const [override, setOverride] = useState(() => {
    try {
      return readConnectionUrl(window.localStorage);
    } catch {
      return "";
    }
  });
  const setSource = value => {
    const next = normalizeConnectionUrl(value);
    try {
      if (next) window.localStorage.setItem(CONNECTION_STORAGE_KEY, next);
      else window.localStorage.removeItem(CONNECTION_STORAGE_KEY);
    } catch {
      // Private browsers may disable storage; keep the source for this session.
    }
    setOverride(next);
  };
  return { url: override || defaultUrl, override, defaultUrl, defaultError, setSource };
};
