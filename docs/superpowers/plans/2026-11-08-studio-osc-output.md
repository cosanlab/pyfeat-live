# Studio OSC output: design

**Goal:** stream what Studio hears and sees (each person's facial movements, emotions, mood, gaze, colour, expression bursts and pair synchrony) to other software over OSC: TouchDesigner, Max/MSP, Resolume, VDMX, Processing, and Ableton via Max for Live. This is Phase 3, item 1 of `2026-11-07-studio-sensory-mapping.md`.

## Decisions

| Question | Decision | Why |
|---|---|---|
| Where the data comes from | The Studio engine (frontend), on every ingested detection | Works for **live and replay** alike; replay never reaches the backend. Values match what drives the sound and scenes (smoothed, per-person baselines, stable person numbers). |
| Who sends UDP | The backend, over a WebSocket from the page | Browsers can't send UDP. The backend is already local and runs in the browser build as well as the desktop app. |
| When it's sent | On each detection (6–25 Hz), not on animation frames | Animation frames pause when the window is hidden or covered. Receivers smooth anyway (TouchDesigner Lag/Filter CHOP, Resolume damping). |
| OSC library | A small encoder written in-repo (~60 lines) | OSC 1.0 encoding is tiny. Adding `python-osc` would mean changing two pinned requirement files and the universal Windows runtime lock for a pure-Python helper. |
| Packet size | Bundles split at ≤ 1400 bytes | macOS caps a UDP datagram at 9216 bytes by default, and LAN paths at roughly the 1500-byte MTU. Three people with every group on comes to about 7 KB per frame. |
| Where it's configured | Customize drawer, new **Outputs** tab, plus a status light on the stage | It's Studio's data, so it lives with Studio's settings and travels with presets. |
| Safety | Loopback only by default; another computer needs an explicit "Allow other computers" switch. The WebSocket rejects foreign browser origins. | Without the origin check, any web page open in the user's browser could make the backend send UDP anywhere. |

## Addresses

The prefix defaults to `/pyfeat` and can be changed. `{n}` is the person number: 1, 2, 3… in arrival order, the same numbering as the mixer. Each address carries one float unless noted, so TouchDesigner's OSC In CHOP turns each into a channel.

| Address | Args | Group | Meaning |
|---|---|---|---|
| `/pyfeat/count` | i | always | People in view |
| `/pyfeat/person/{n}/present` | i | always | 1 while in view; one 0 when they leave |
| `/pyfeat/person/{n}/x` | f | always | Horizontal position on screen, 0..1 (mirror-corrected in Live) |
| `/pyfeat/person/{n}/au/AU12` | f | Facial movements | Smoothed AU intensity, 0..1 |
| `/pyfeat/person/{n}/auz/AU12` | f | Facial movements, relative | z against the person's own baseline (≈0 at rest, 2–4 for a clear movement) |
| `/pyfeat/person/{n}/emotion/happiness` | f | Emotions | Smoothed probability, 0..1 (7 emotions incl. `neutral`) |
| `/pyfeat/person/{n}/valence`, `…/arousal`, `…/energy` | f | Mood & energy | Valence −1..1, arousal −1..1, expressiveness ≥0 |
| `/pyfeat/person/{n}/gaze/x`, `…/gaze/y` | f | Eyes | Eye direction relative to the head: right+ / up+, −1..1 |
| `/pyfeat/person/{n}/gaze/away` | f | Eyes | Radians off straight ahead |
| `/pyfeat/person/{n}/gaze/movement` | f | Eyes | Eye-movement z (glances spike) |
| `/pyfeat/person/{n}/color` | f f f | Colour | The colour the art scenes paint this person (r, g, b 0..1), following the Colour from setting and palette |
| `/pyfeat/person/{n}/onset/AU12` | f | Events | Fires on each expression onset; arg = strength |
| `/pyfeat/person/{n}/glance` | f | Events | Fires on each glance; arg = strength |
| `/pyfeat/sync` | f | Synchrony | Strongest pair synchrony right now, 0..1 |
| `/pyfeat/sync/{a}/{b}` | f | Synchrony | Pair synchrony, a < b |
| `/pyfeat/mimicry` | i i s f | Synchrony | Leader, follower, feature, latency (s) |
| `/pyfeat/group/valence`, `/pyfeat/group/energy` | f | Mood & energy | Mean over people in view |
| `/pyfeat/test` | s | n/a | Sent by the "Send test" button |

## Pieces

1. **`backend/osc.py`**: `encode_message(address, args)` and `encode_bundles(messages, max_bytes=1400)`. Types: `int` → i, `float` → f, `str` → s; NaN and inf are dropped.
2. **`backend/routers/studio.py`**: WebSocket `/api/studio/osc`.
   - Client → server: `{"type":"config","host","port","allowLan"}`, `{"type":"frame","msgs":[[addr,[args]],…]}`, `{"type":"test"}`.
   - Server → client: `{"type":"status","ok","error"?}` after each config, and `{"type":"stats","messages","packets","bytes","errors"}` each second.
   - Validates the origin, host and port. A refused UDP send (no listener) counts as an error but isn't fatal.
3. **Engine `setOutputListener(cb)`**: after each non-silent ingest, emits an `OutputFrame`. It holds per-person views (the same shape as the scene slots plus the person number), that frame's onsets (including glances), pairs and mimicry. Outputs don't drain the scenes' queues.
4. **`studio/osc.ts`**:
   - `OscSettings` + `DEFAULT_OSC` + `normalizeOsc`
   - `OscFrameBuilder.build(frame, settings, art)` → messages; it tracks departures to send `present 0`
   - `OscLink`: WebSocket connection, config, send, test, stats, and reconnect with backoff while enabled. It drops a frame rather than queueing when the socket is backed up.
5. **UI**:
   - The Outputs tab has: an on/off switch; host and port; Allow other computers; prefix; what to send; Send test; live status (messages/s, last error); and a collapsible address reference.
   - A small status light top-left of the stage: green while sending, amber while connecting, red on error. It fades in stage mode like the other controls.
   - Settings persist under `pyfeat.studio.osc.v1`. They're kept out of presets because a preset shouldn't silently start sending.

## Testing

- **Backend:**
  - Encoder bytes against the OSC 1.0 spec's worked examples.
  - Bundle splitting.
  - WebSocket end to end: a real UDP socket on an ephemeral port receives and decodes a frame.
  - Origin rejection; LAN host refused without `allowLan`.
- **Frontend:**
  - Builder addresses and arg types for each group.
  - `present 0` on departure; onsets and glances map to their addresses.
  - Engine output listener: fires per ingest, not when silent, and doesn't steal scene onsets.
- **Manual:** a UDP listener script printing decoded OSC while a recording replays. TouchDesigner (OSC In CHOP) is checked by the user.

## Later

- MIDI out: CC from continuous features, notes from onsets, through `mido` + `python-rtmidi`. That's a native dependency, so it needs lock and Windows work.
- Raw per-detection feed from the plain Live tab without Studio.
- Receiving OSC to drive Studio (scene changes from a controller).
