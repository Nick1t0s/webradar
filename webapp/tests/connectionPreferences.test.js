import assert from "node:assert/strict";
import { test } from "node:test";
import { CONNECTION_STORAGE_KEY, getDefaultConnection, normalizeConnectionUrl, readConnectionUrl } from "../src/utilities/connectionPreferences.js";

test("explicit source accepts remote hosts and secure endpoints independently of HTTP", () => {
  assert.equal(normalizeConnectionUrl(" ws://192.168.1.20:22006/cs2_webradar "), "ws://192.168.1.20:22006/cs2_webradar");
  assert.equal(normalizeConnectionUrl("wss://radar.example/data"), "wss://radar.example/data");
  assert.equal(normalizeConnectionUrl("ws://[::1]:22006/cs2_webradar"), "ws://[::1]:22006/cs2_webradar");
  assert.equal(normalizeConnectionUrl("  "), "");
});

test("invalid sources fail before replacing a working connection", () => {
  for (const value of ["127.0.0.1:22006", "https://example.com", "ws://", "ws://host:99999", "ws://host:0", "ws://user:secret@host:22006", "ws://host/path#fragment", "ws://host/a b"]) {
    assert.throws(() => normalizeConnectionUrl(value), Error, value);
  }
});

test("connection persistence uses its own key and tolerates disabled or corrupt storage", () => {
  let readKey;
  assert.equal(readConnectionUrl({ getItem: key => { readKey = key; return "ws://host:22006/cs2_webradar"; } }), "ws://host:22006/cs2_webradar");
  assert.equal(readKey, CONNECTION_STORAGE_KEY);
  assert.equal(readConnectionUrl({ getItem: () => "garbage" }), "");
  assert.equal(readConnectionUrl({ getItem: () => { throw new Error("storage blocked"); } }), "");
});


test("invalid configured default keeps the settings UI available with an actionable error", () => {
  const location = new URL("http://192.168.1.20:5173/");
  const fallback = getDefaultConnection(location, { useLocalhost: false });
  const invalid = getDefaultConnection(location, { override: "https://wrong.example", useLocalhost: false });
  assert.equal(invalid.url, fallback.url);
  assert.match(invalid.error, /Configured default source is invalid/);
  const valid = getDefaultConnection(location, { override: "wss://helper.example/data", useLocalhost: false });
  assert.equal(valid.url, "wss://helper.example/data");
  assert.equal(valid.error, "");
});
