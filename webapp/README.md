# React + Vite

## Radar display

The radar fits both the width and height of the available window, including
portrait monitors and resized minimap overlays. Team sidebars are shown on
landscape screens at least 1024px wide; portrait screens use the full width
for the map.

Open **Settings → Map Rotation** to choose an angle, rotate 90° in either
direction, or reset to 0°. The angle is saved in the browser and is also
available in minimap settings. The map and all position layers rotate together;
at Zoom 1 with Follow Me off the full map fits even at diagonal angles. Increasing Zoom intentionally
shows only part of the map, with Follow Me available as before.

Run `npm test` for viewport geometry checks and `npm run build` for a production
build.

**Self Color**, **Teammate Color** and **Enemy Color** in Settings control radar
markers independently, including their borders and glow. Choose a preset or a
custom colour. Defaults are green for yourself and teammates, red for enemies.
These preferences are saved in the browser and also work in minimap mode;
no helper/backend changes are needed.

Enable **Settings → Rotate with view** to keep your local player's view facing
up. Turning is smoothed across the 0°/360° boundary; the map uses a constant fit
so it stays inside the window without changing size as you turn. The manual
angle is preserved and restored when this mode is disabled (also used when no
living local player with a valid view angle is available). Combine with Zoom
and Follow Me to keep yourself centred. The option is saved and works in minimap
settings too. Player names, height markers, map callouts, grenade labels, dropped
weapon labels and the C4 icon stay upright for both manual and automatic rotation.

## Multiple viewers (no account needed)

Open the same radar URL on each device, then choose yourself in **Settings → Your
Player**. Your selection determines your marker, teammates/enemies, view rotation,
following, height markers and map floor. A new player profile starts with Rotate
with view and Follow Me enabled. Following now keeps that player exactly centred,
including near map edges and at Zoom 1; turn Follow Me off to see the entire map.

Each browser saves its own selection and display profiles (colours, zoom, rotation
and other display options). Switching players restores their saved profile; tabs
can select different players independently. Existing settings are kept in the
automatic helper-player profile. Real players are remembered by Steam ID, so
nicknames, slots and team changes don't change who you follow. Bots use their
slot and name. If a selected player leaves, the radar waits for that identity
instead of following someone else; you can choose another player in Settings.
The selector also works in minimap settings.

The helper already broadcasts the same game frame to multiple WebSocket clients;
perspective and display settings stay in each browser. Joining, changing player
or changing display preferences sends no settings to other viewers or the helper.
Explicit **Helper Auto Update (shared)** and **Refresh offsets** actions still
control the shared helper, subject to its existing access restrictions. The ESP
overlay continues to use the helper's own camera matrix and local player.

This template provides a minimal setup to get React working in Vite with HMR and some ESLint rules.

Currently, two official plugins are available:

- [@vitejs/plugin-react](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react/README.md) uses [Babel](https://babeljs.io/) for Fast Refresh
- [@vitejs/plugin-react-swc](https://github.com/vitejs/vite-plugin-react-swc) uses [SWC](https://swc.rs/) for Fast Refresh
