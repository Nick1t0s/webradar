import { HELPER_VIEWER } from "./viewerPerspective.js";

const VIEWER_KEY = "radarViewerId";
const settingsKey = id => id === HELPER_VIEWER ? "radarSettings" : `radarSettings:viewer:${id}`;
const read = (storage, key) => {
  try { return storage?.getItem(key); } catch { return null; }
};

export const loadViewerSettings = (storage, id, defaults, initial = defaults) => {
  try {
    const saved = JSON.parse(read(storage, settingsKey(id)) ?? "null");
    return saved && typeof saved === "object" && !Array.isArray(saved)
      ? { ...defaults, ...saved } : { ...initial };
  } catch {
    return { ...initial };
  }
};

export const loadViewerPreferences = (storage, session, defaults) => {
  // Tabs retain their own player even when another tab chooses someone else.
  const id = read(session, VIEWER_KEY) || read(storage, VIEWER_KEY) || HELPER_VIEWER;
  const viewerId = typeof id === "string" && /^(helper|steam:\d+|slot:.*)$/.test(id) ? id : HELPER_VIEWER;
  const legacy = loadViewerSettings(storage, HELPER_VIEWER, defaults);
  return { viewerId, settings: loadViewerSettings(storage, viewerId, defaults, legacy) };
};

export const saveViewerPreferences = (storage, session, { viewerId, settings }) => {
  // Storage can be unavailable in private/embedded browsers; the view still works.
  try { storage?.setItem(settingsKey(viewerId), JSON.stringify(settings)); } catch { /* memory only */ }
  try { storage?.setItem(VIEWER_KEY, viewerId); } catch { /* memory only */ }
  try { session?.setItem(VIEWER_KEY, viewerId); } catch { /* memory only */ }
};
