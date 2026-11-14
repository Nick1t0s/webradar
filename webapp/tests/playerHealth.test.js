import assert from "node:assert/strict";
import { test } from "node:test";
import { getPlayerHealthFill } from "../src/utilities/playerHealth.js";

test("HP fills from the actual bottom of the marker upwards", () => {
  assert.deepEqual(getPlayerHealthFill(100), { health: 100, stop: 25 });
  assert.deepEqual(getPlayerHealthFill(50), { health: 50, stop: 50 });
  assert.deepEqual(getPlayerHealthFill(25), { health: 25, stop: 62.5 });
  assert.deepEqual(getPlayerHealthFill(0), { health: 0, stop: 75 });
});

test("invalid or missing health preserves the existing full-colour marker", () => {
  for (const value of [undefined, null, NaN, Infinity, "25"]) {
    assert.equal(getPlayerHealthFill(value).health, 100);
  }
  assert.equal(getPlayerHealthFill(-10).health, 0);
  assert.equal(getPlayerHealthFill(150).health, 100);
});

test("the fill level tracks the rotated teardrop's actual height at every heading", () => {
  for (let angle = 0; angle < 360; angle++) {
    const radians = angle * Math.PI / 180;
    // Independently sample the circle and the pointed corner of the silhouette.
    const heights = Array.from({ length: 360 }, (_, point) => Math.sin((point + angle) * Math.PI / 180) / 2);
    heights.push(-0.5 * Math.sin(radians) + 0.5 * Math.cos(radians));
    const top = Math.min(...heights), bottom = Math.max(...heights);
    for (const hp of [0, 1, 10, 25, 50, 75, 99, 100]) {
      const { stop } = getPlayerHealthFill(hp, angle);
      const boundary = stop / 50 - 1;
      assert.ok(Math.abs((bottom - boundary) / (bottom - top) - hp / 100) < 1e-10);
    }
  }
});
