import assert from "node:assert/strict";
import { test } from "node:test";
import { getPlayerIdentity, getViewerPerspective, HELPER_VIEWER } from "../src/utilities/viewerPerspective.js";
import { getPlayerColor } from "../src/utilities/playerColors.js";
import { getRadarTransform } from "../src/utilities/radarViewport.js";

const players = [
  { m_idx: 1, m_name: "Same name", m_steam_id: "76561198000000001", m_team: 2, m_is_local: true, m_eye_angle: 90 },
  { m_idx: 2, m_name: "Same name", m_steam_id: "76561198000000002", m_team: 3, m_is_local: false, m_eye_angle: 180 },
  { m_idx: 3, m_name: "Teammate", m_steam_id: "76561198000000003", m_team: 3, m_is_local: false, m_eye_angle: 0 },
];

test("viewers derive different selves, teams, colours and rotations from the same immutable frame", () => {
  const before = structuredClone(players);
  const a = getViewerPerspective(players, getPlayerIdentity(players[0]), 2);
  const b = getViewerPerspective(players, getPlayerIdentity(players[1]), 2);
  assert.equal(a.localTeam, 2);
  assert.equal(b.localTeam, 3);
  assert.deepEqual(a.players.map(p => p.m_is_local), [true, false, false]);
  assert.deepEqual(b.players.map(p => p.m_is_local), [false, true, false]);
  const settings = { selfColor: "white", teammateColor: "blue", enemyColor: "red", followView: true };
  assert.deepEqual(a.players.map(p => getPlayerColor(p, a.localTeam, settings)), ["white", "red", "red"]);
  assert.deepEqual(b.players.map(p => getPlayerColor(p, b.localTeam, settings)), ["red", "white", "blue"]);
  assert.equal(getRadarTransform(800, settings, null, a.selectedPlayer).rotation, 0);
  assert.equal(getRadarTransform(800, settings, null, b.selectedPlayer).rotation, 90);
  assert.deepEqual(players, before);
});

test("Steam identity survives renaming, slot changes and team switches", () => {
  const selected = getPlayerIdentity(players[1]);
  const updated = [{ ...players[1], m_idx: 9, m_name: "Renamed", m_team: 2 }];
  const view = getViewerPerspective(updated, selected, 3);
  assert.equal(view.localTeam, 2);
  assert.equal(view.players[0].m_is_local, true);
  assert.equal(view.missing, false);
});

test("an absent selected player never silently follows the helper or a reused slot", () => {
  const selected = getPlayerIdentity(players[1]);
  const view = getViewerPerspective([players[0], { ...players[1], m_steam_id: "76561198000000004" }], selected, 2);
  assert.equal(view.missing, true);
  assert.equal(view.localTeam, 0);
  assert.equal(view.selectedPlayer, undefined);
  assert.ok(view.players.every(p => !p.m_is_local));
});

test("helper mode preserves legacy behaviour and dead players remain selected", () => {
  assert.equal(getViewerPerspective(players, HELPER_VIEWER, 3).localTeam, 2);
  assert.equal(getViewerPerspective([], HELPER_VIEWER, 3).localTeam, 3);
  const dead = { ...players[1], m_is_dead: true };
  assert.equal(getViewerPerspective([dead], getPlayerIdentity(dead), 2).players[0].m_is_local, true);
});

test("bots and duplicate names have distinct identities without binding to a new name in a reused slot", () => {
  const bot = { m_idx: 2, m_name: "Bot", m_steam_id: "0" };
  assert.notEqual(getPlayerIdentity(bot), getPlayerIdentity({ ...bot, m_idx: 3 }));
  assert.notEqual(getPlayerIdentity(bot), getPlayerIdentity({ ...bot, m_name: "New Bot" }));
  assert.notEqual(getPlayerIdentity(players[0]), getPlayerIdentity(players[1]));
});
