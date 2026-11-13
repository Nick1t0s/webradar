import assert from "node:assert/strict";
import { test } from "node:test";
import { getPlayerColor } from "../src/utilities/playerColors.js";

test("old saved settings get green self/teammates and red enemies", () => {
  assert.equal(getPlayerColor({ m_is_local: true, m_team: 2 }, 2, { zoom: 2 }), "#4ade80");
  assert.equal(getPlayerColor({ m_team: 2 }, 2), "#4ade80");
  assert.equal(getPlayerColor({ m_team: 3 }, 2), "#ef4444");
});

test("custom self colour takes priority and teammate/enemy colours follow team changes", () => {
  const settings = { selfColor: "#ffffff", teammateColor: "#00cfff", enemyColor: "#ffdd00" };
  assert.equal(getPlayerColor({ m_is_local: true, m_team: 2 }, 3, settings), settings.selfColor);
  assert.equal(getPlayerColor({ m_team: 2 }, 2, settings), settings.teammateColor);
  assert.equal(getPlayerColor({ m_team: 2 }, 3, settings), settings.enemyColor);
  assert.equal(getPlayerColor({ m_team: 3 }, 3, settings), settings.teammateColor);
});
