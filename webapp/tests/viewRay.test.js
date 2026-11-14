import assert from "node:assert/strict";
import { test } from "node:test";
import { getViewRay, VIEW_RAY_TARGET_RADIUS } from "../src/utilities/viewRay.js";
import { getViewerPerspective, getPlayerIdentity } from "../src/utilities/viewerPerspective.js";

const player = (id, x, y, extra = {}) => ({
  m_idx: id, m_steam_id: String(id), m_team: 2, m_is_dead: false, m_health: 100,
  m_position: { x, y, z: 0 }, ...extra,
});
const local = player(1, 0, 0, { m_is_local: true, m_eye_angle: 0 });

test("the ray follows game yaw in every quadrant, including negative angles", () => {
  for (const yaw of [0, 45, 90, 135, 180, -135, -90, -45, 359]) {
    const radians = yaw * Math.PI / 180;
    const target = player(2, Math.cos(radians) * 500, Math.sin(radians) * 500);
    const result = getViewRay({ ...local, m_eye_angle: yaw }, [target]);
    assert.equal(result.target, target);
    assert.ok(Math.abs(result.distance - (500 - VIEW_RAY_TARGET_RADIUS)) < 1e-8);
  }
});

test("only the first ray/circle intersection is highlighted, independent of player order", () => {
  const near = player(2, 200, 0), far = player(3, 400, 0);
  assert.equal(getViewRay(local, [far, near]).target, near);
  assert.equal(getViewRay(local, [near, far]).target, near);
  const tangent = player(4, 200, VIEW_RAY_TARGET_RADIUS);
  const nearerSurface = player(5, 210, 0);
  assert.equal(getViewRay(local, [tangent, nearerSurface]).target, nearerSurface);
});

test("behind, sideways, dead and invalid players are not targets", () => {
  const result = getViewRay(local, [
    local, player(2, -200, 0), player(3, 200, VIEW_RAY_TARGET_RADIUS + 1),
    player(4, 200, 0, { m_is_dead: true }), player(5, 200, 0, { m_health: 0 }),
    player(6, NaN, 0), player(7, 200, Infinity),
  ]);
  assert.equal(result.target, null);
  assert.equal(result.distance, Infinity);
});

test("vertical position is deliberately ignored; shown teammates can be targets", () => {
  const target = player(2, 200, 0, { m_position: { x: 200, y: 0, z: 100000 } });
  assert.equal(getViewRay(local, [target]).target, target);
  assert.equal(getViewRay(local, [target], { showAllies: false, localTeam: 2 }).target, null);
  assert.equal(getViewRay(local, [target], { showAllies: false, localTeam: 3 }).target, target);
});

test("missing/dead local players and invalid view angles produce no ray", () => {
  for (const me of [null, undefined, { ...local, m_is_dead: true }, { ...local, m_health: 0 },
    { ...local, m_eye_angle: null }, { ...local, m_eye_angle: NaN }, { ...local, m_position: null }]) {
    assert.equal(getViewRay(me, []), null);
  }
});

test("the ray belongs to the browser-selected player, not the helper player", () => {
  const other = player(2, 200, 0, { m_team: 3, m_eye_angle: 180 });
  const view = getViewerPerspective([local, other], getPlayerIdentity(other), 2);
  const result = getViewRay(view.selectedPlayer, view.players);
  assert.equal(result.target.m_idx, local.m_idx);
  assert.equal(result.direction.x, -1);
});
