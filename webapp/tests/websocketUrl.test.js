import assert from "node:assert/strict";
import { test } from "node:test";
import { getWebSocketUrl } from "../src/utilities/websocketUrl.js";

test("HTTP site port is independent of the WebSocket data port", () => {
  assert.equal(getWebSocketUrl(new URL("http://91.195.136.176:5173/")), "ws://91.195.136.176:22006/cs2_webradar");
  assert.equal(getWebSocketUrl(new URL("http://example.com:18080/")), "ws://example.com:22006/cs2_webradar");
});

test("localhost, LAN and IPv6 use their hostname on the data port", () => {
  for (const hostname of ["localhost", "127.0.0.1", "192.168.1.5", "[::1]"]) {
    assert.equal(getWebSocketUrl(new URL(`http://${hostname}:5173/`)), `ws://${hostname}:22006/cs2_webradar`);
  }
});

test("HTTPS selects secure WebSocket on its independent port", () => {
  assert.equal(getWebSocketUrl(new URL("https://radar.example.com/")), "wss://radar.example.com:22006/cs2_webradar");
  assert.equal(getWebSocketUrl(new URL("https://radar.example.com:8443/?mode=minimap")), "wss://radar.example.com:22006/cs2_webradar");
});

test("explicit endpoint and legacy localhost mode retain precedence", () => {
  const location = new URL("http://91.195.136.176:5173/");
  assert.equal(getWebSocketUrl(location, { override: "wss://tunnel.example.com:2443/cs2_webradar", useLocalhost: true }), "wss://tunnel.example.com:2443/cs2_webradar");
  assert.equal(getWebSocketUrl(location, { useLocalhost: true }), "ws://localhost:22006/cs2_webradar");
  assert.equal(getWebSocketUrl(location, { override: "" }), "ws://91.195.136.176:22006/cs2_webradar");
});

test("invalid endpoint overrides fail before opening a connection", () => {
  const location = new URL("http://localhost:5173/");
  for (const override of ["localhost:22006", "http://localhost:5173/", "ws://", "ws://host:99999/", "ws://user:secret@host/", "ws://host/#fragment"]) {
    assert.throws(() => getWebSocketUrl(location, { override }));
  }
});
