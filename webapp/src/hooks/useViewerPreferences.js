import { useEffect, useState } from "react";
import { HELPER_VIEWER } from "../utilities/viewerPerspective";
import { loadViewerPreferences, loadViewerSettings, saveViewerPreferences } from "../utilities/viewerPreferences";

const browserStorage = name => {
  try { return window[name]; } catch { return undefined; }
};

export const useViewerPreferences = defaults => {
  const storage = browserStorage("localStorage");
  const session = browserStorage("sessionStorage");
  const [preferences, setPreferences] = useState(() => loadViewerPreferences(storage, session, defaults));

  useEffect(() => {
    saveViewerPreferences(storage, session, preferences);
  }, [preferences, storage, session]);

  const setSettings = update => setPreferences(previous => ({
    ...previous,
    settings: typeof update === "function" ? update(previous.settings) : update,
  }));

  const selectViewer = viewerId => setPreferences(previous => {
    if (viewerId === previous.viewerId) return previous;
    const initial = viewerId === HELPER_VIEWER ? previous.settings
      : { ...previous.settings, followView: true, followMe: true };
    return { viewerId, settings: loadViewerSettings(storage, viewerId, defaults, initial) };
  });

  return { ...preferences, setSettings, selectViewer };
};
