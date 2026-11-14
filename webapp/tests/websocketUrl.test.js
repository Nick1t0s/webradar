import assert from "node:assert/strict";
import { test } from "node:test";
import { getWebSocketUrl } from "../src/utilities/websocketUrl.js";

test("public HTTP uses the exposed page port instead of an unforwarded 22006", () => {
  assert.equal(getWebSocketUrl(new URL("http://91.195.136.176:5173/")), "ws://91.195.136.176:5173/cs2_webradar");
  assert.equal(getWebSocketUrl(new URL("http://example.com:18080/")), "ws://example.com:18080/cs2_webradar");
});

test("localhost, LAN and IPv6 preserve their page authority", () => {
  for (const host of ["localhost:5173", "127.0.0.1:5173", "192.168.1.5:5173", "[::1]:5173"]) {
    assert.equal(getWebSocketUrl(new URL(`http://${host}/`)), `ws://${host}/cs2_webradar`);
  }
});

test("HTTPS and custom reverse-proxy ports use secure same-origin WebSockets", () => {
  assert.equal(getWebSocketUrl(new URL("https://radar.example.com/")), "wss://radar.example.com/cs2_webradar");
  assert.equal(getWebSocketUrl(new URL("https://radar.example.com:8443/?mode=minimap")), "wss://radar.example.com:8443/cs2_webradar");
});

test("explicit tunnel override and legacy localhost mode retain precedence", () => {
  const location = new URL("http://91.195.136.176:5173/");
  assert.equal(getWebSocketUrl(location, { override: "wss://tunnel.example.com/cs2_webradar", useLocalhost: true }), "wss://tunnel.example.com/cs2_webradar");
  assert.equal(getWebSocketUrl(location, { useLocalhost: true }), "ws://localhost:22006/cs2_webradar");
  assert.equal(getWebSocketUrl(location, { override: "" }), "ws://91.195.136.176:5173/cs2_webradar");
});
