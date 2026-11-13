import assert from "node:assert/strict";
import { test } from "node:test";
import { getRadarTransform, normalizeRotation } from "../src/utilities/radarViewport.js";

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

test("following centres the player before rotation while keeping zoom inside map edges", () => {
  for (const angle of [0, 45, 90, 180, 270]) {
    const centred = getRadarTransform(800, { zoom: 2, mapRotation: angle }, { x: 0.4, y: 0.6 });
    assert.equal(centred.tx + 0.4 * 800 * centred.zoom, 400);
    assert.equal(centred.ty + 0.6 * 800 * centred.zoom, 400);
    const edge = getRadarTransform(800, { zoom: 2, mapRotation: angle }, { x: 0, y: 1 });
    assert.equal(edge.tx, 0);
    assert.equal(edge.ty, -800);
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
