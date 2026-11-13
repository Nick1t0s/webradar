import assert from "node:assert/strict";
import { test } from "node:test";
import { getNearestRotation, getRadarTransform, normalizeRotation } from "../src/utilities/radarViewport.js";

test("the full map fits portrait, landscape and small overlay frames at every angle", () => {
  for (const [width, height] of [[1080, 1920], [1920, 1080], [390, 844], [320, 240]]) {
    const size = Math.min(width, height);
    for (let angle = 0; angle < 360; angle++) {
      const { rotation, fit } = getRadarTransform(size, { mapRotation: angle });
      const radians = rotation * Math.PI / 180;
      for (const x of [-size / 2, size / 2]) {
        for (const y of [-size / 2, size / 2]) {
          const rx = (x * Math.cos(radians) - y * Math.sin(radians)) * fit;
          const ry = (x * Math.sin(radians) + y * Math.cos(radians)) * fit;
          assert.ok(Math.abs(rx) <= width / 2 + 1e-8);
          assert.ok(Math.abs(ry) <= height / 2 + 1e-8);
        }
      }
    }
  }
});

test("following centres the player before rotation, including map edges and Zoom 1", () => {
  for (const angle of [0, 45, 90, 180, 270]) {
    const centred = getRadarTransform(800, { zoom: 2, mapRotation: angle }, { x: 0.4, y: 0.6 });
    assert.equal(centred.tx + 0.4 * 800 * centred.zoom, 400);
    assert.equal(centred.ty + 0.6 * 800 * centred.zoom, 400);
    const edge = getRadarTransform(800, { zoom: 2, mapRotation: angle }, { x: 0, y: 1 });
    assert.equal(edge.tx, 400);
    assert.equal(edge.ty, -1200);
    const whole = getRadarTransform(800, { zoom: 1, mapRotation: angle }, { x: 0.1, y: 0.9 });
    assert.equal(whole.tx + 0.1 * 800, 400);
    assert.equal(whole.ty + 0.9 * 800, 400);
  }
});

test("rotation wraps and invalid stored values fall back to a usable viewport", () => {
  assert.equal(normalizeRotation(-90), 270);
  assert.equal(normalizeRotation(450), 90);
  assert.equal(normalizeRotation("invalid"), 0);
  assert.deepEqual(getRadarTransform(800, { zoom: "invalid", mapRotation: null }), {
    rotation: 0, fit: 1, zoom: 1, tx: 0, ty: 0,
  });
  assert.equal(getRadarTransform(800, { zoom: 10 }).zoom, 4);
});

test("heading-up rotates the local view vector upwards at every game yaw", () => {
  for (let yaw = -180; yaw <= 360; yaw++) {
    const { rotation, fit } = getRadarTransform(800, { followView: true, mapRotation: 37 }, null, { m_eye_angle: yaw });
    const heading = yaw * Math.PI / 180;
    const angle = rotation * Math.PI / 180;
    const x = Math.cos(heading), y = -Math.sin(heading);
    assert.ok(Math.abs(x * Math.cos(angle) - y * Math.sin(angle)) < 1e-10);
    assert.ok(Math.abs(x * Math.sin(angle) + y * Math.cos(angle) + 1) < 1e-10);
    assert.equal(fit, Math.SQRT1_2);
    assert.ok(fit * (Math.abs(Math.cos(angle)) + Math.abs(Math.sin(angle))) <= 1 + 1e-10);
  }
});

test("missing, dead and invalid local views use the saved manual angle", () => {
  const settings = { followView: true, mapRotation: 42 };
  for (const player of [undefined, null, {}, { m_eye_angle: null }, { m_eye_angle: NaN },
    { m_eye_angle: Infinity }, { m_eye_angle: 90, m_is_dead: true }]) {
    assert.equal(getRadarTransform(800, settings, null, player).rotation, 42);
  }
  assert.equal(getRadarTransform(800, { ...settings, followView: false }, null, { m_eye_angle: 90 }).rotation, 42);
});

test("view rotation and marker rotation cross angular boundaries by the shortest path", () => {
  assert.equal(getNearestRotation(179, -179), 181);
  assert.equal(getNearestRotation(-179, 179), -181);
  assert.equal(getNearestRotation(359, 1), 361);
  assert.equal(getNearestRotation(1, 359), -1);
  assert.equal(getNearestRotation(1080, 1), 1081);
  assert.equal(getNearestRotation(-1080, 359), -1081);
});
