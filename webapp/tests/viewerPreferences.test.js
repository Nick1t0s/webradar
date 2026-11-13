import assert from "node:assert/strict";
import { test } from "node:test";
import { loadViewerPreferences, loadViewerSettings, saveViewerPreferences } from "../src/utilities/viewerPreferences.js";

const storage = () => {
  const values = new Map();
  return { getItem: key => values.get(key) ?? null, setItem: (key, value) => values.set(key, value) };
};
const defaults = { selfColor: "green", zoom: 1, followView: false };

test("existing radarSettings migrate without losing custom colours or the manual angle", () => {
  const local = storage();
  local.setItem("radarSettings", JSON.stringify({ selfColor: "purple", mapRotation: 45 }));
  assert.deepEqual(loadViewerPreferences(local, storage(), defaults), {
    viewerId: "helper", settings: { ...defaults, selfColor: "purple", mapRotation: 45 },
  });
});

test("player profiles and separate browser storage never overwrite one another", () => {
  const local = storage(), otherBrowser = storage(), a = storage(), b = storage();
  const first = { viewerId: "steam:1", settings: { ...defaults, selfColor: "cyan", zoom: 2 } };
  const second = { viewerId: "steam:2", settings: { ...defaults, selfColor: "yellow", zoom: 3 } };
  saveViewerPreferences(local, a, first);
  saveViewerPreferences(local, b, second);
  saveViewerPreferences(otherBrowser, storage(), { ...first, settings: { ...defaults, selfColor: "white" } });
  assert.deepEqual(loadViewerPreferences(local, a, defaults), first);
  assert.deepEqual(loadViewerPreferences(local, b, defaults), second);
  assert.equal(loadViewerPreferences(local, storage(), defaults).viewerId, "steam:2");
  assert.equal(loadViewerPreferences(otherBrowser, storage(), defaults).settings.selfColor, "white");
  assert.equal(loadViewerSettings(local, "steam:1", defaults).selfColor, "cyan");
});

test("new profiles can inherit current settings without modifying the helper profile", () => {
  const local = storage(), session = storage();
  saveViewerPreferences(local, session, { viewerId: "helper", settings: { ...defaults, selfColor: "purple" } });
  const initial = { ...defaults, selfColor: "cyan", followView: true };
  assert.deepEqual(loadViewerSettings(local, "steam:2", defaults, initial), initial);
  assert.equal(loadViewerSettings(local, "helper", defaults).selfColor, "purple");
});

test("malformed or blocked storage doesn't prevent using the radar", () => {
  const local = storage();
  for (const value of ["{", "null", "[]", "42"]) {
    local.setItem("radarSettings", value);
    assert.deepEqual(loadViewerPreferences(local, storage(), defaults).settings, defaults);
  }
  const blocked = { getItem() { throw new Error("blocked"); }, setItem() { throw new Error("blocked"); } };
  assert.deepEqual(loadViewerPreferences(blocked, blocked, defaults), { viewerId: "helper", settings: defaults });
  assert.doesNotThrow(() => saveViewerPreferences(blocked, blocked, { viewerId: "helper", settings: defaults }));
});
