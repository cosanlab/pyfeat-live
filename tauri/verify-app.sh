#!/bin/bash
# Quick smoke test for a locally-built .app.
#
# Run after `tauri build --bundles app` finishes:
#
#     APPLE_SIGNING_IDENTITY="-" ./node_modules/.bin/tauri build --bundles app
#     ./verify-app.sh
#
# What this checks:
#   - The .app exists and has the expected internal layout
#   - Info.plist has NSCameraUsageDescription
#   - entitlements were applied (codesign --display)
#   - the bundled uv binary is present and executable
#   - the bundled pyfeatlive/ source tree is present
#   - Tauri externalBin's host-triple suffix is right
#
# It does NOT actually launch the app — that's an interactive
# smoke test best done by hand (open Py-feat\ Live.app and
# watch the splash do its thing, then check the user-data dir).

set -euo pipefail

APP="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/src-tauri/target/release/bundle/macos/Py-feat Live.app"

if [ ! -d "$APP" ]; then
  echo "❌ .app not found at: $APP" >&2
  echo "   Did you run 'tauri build --bundles app' yet?" >&2
  exit 1
fi

ok() { printf "✅ %s\n" "$*"; }
fail() { printf "❌ %s\n" "$*" >&2; }
check() {
  local label="$1"; shift
  if "$@" >/dev/null 2>&1; then ok "$label"; else fail "$label"; return 1; fi
}

echo "Inspecting: $APP"
echo

# Layout
test -f "$APP/Contents/MacOS/pyfeatlive-tauri" \
  && ok "main binary present" \
  || { fail "main binary missing"; exit 1; }

# Tauri's macOS bundler strips the host-triple suffix from externalBin
# at install time — `Contents/MacOS/uv-<triple>` becomes
# `Contents/MacOS/uv`. The Rust code in lib.rs::uv_binary_path() looks
# for both naming conventions.
test -f "$APP/Contents/MacOS/uv" \
  && ok "bundled uv: Contents/MacOS/uv" \
  || { fail "missing Contents/MacOS/uv"; exit 1; }

# Resources we declared in tauri.conf.json. Tauri places them under
# Resources/, not Resources/_up_/ — that earlier guess was wrong.
res="$APP/Contents/Resources"
test -d "$res/pyfeatlive" \
  && ok "pyfeatlive/ resource present" \
  || fail "pyfeatlive/ resource missing"

test -f "$res/runtime/sidecar.py" \
  && ok "runtime/sidecar.py resource present" \
  || fail "runtime/sidecar.py resource missing"

test -f "$res/runtime/requirements.txt" \
  && ok "runtime/requirements.txt resource present" \
  || fail "runtime/requirements.txt resource missing"

# Info.plist
plist="$APP/Contents/Info.plist"
if /usr/libexec/PlistBuddy -c "Print :NSCameraUsageDescription" "$plist" >/dev/null 2>&1; then
  desc=$(/usr/libexec/PlistBuddy -c "Print :NSCameraUsageDescription" "$plist")
  ok "NSCameraUsageDescription set: '${desc:0:60}...'"
else
  fail "NSCameraUsageDescription NOT in Info.plist"
fi

# Code signature (ad-hoc: signature is -)
sig=$(codesign --display --verbose=2 "$APP" 2>&1 | grep -E "^Authority|^Signature" | head -2)
if [ -n "$sig" ]; then
  ok "signed:"
  echo "$sig" | sed 's/^/    /'
else
  fail "no signature info"
fi

# Entitlements (the camera + JIT exemptions we declared)
ents=$(codesign --display --entitlements - "$APP" 2>&1 | tr -d '\0')
for key in \
  "com.apple.security.device.camera" \
  "com.apple.security.cs.allow-jit" \
  "com.apple.security.cs.disable-library-validation"; do
  if echo "$ents" | grep -q "$key"; then
    ok "entitlement: $key"
  else
    fail "missing entitlement: $key"
  fi
done

# Size sanity check — should be small (Tauri shell + uv only, ~50-100MB)
size=$(du -sh "$APP" | awk '{print $1}')
echo
echo "Bundle size: $size  (expected ~50-100MB; all heavy deps install on first run)"

echo
echo "Open the .app to drive the runtime install:"
echo "    open \"$APP\""
echo
echo "Then watch:"
echo "    tail -f \"\$HOME/Library/Application Support/com.cosanlab.pyfeatlive/runtime/venv/_install.log\" 2>/dev/null"
echo "    ls -la \"\$HOME/Library/Application Support/com.cosanlab.pyfeatlive/\""
echo
echo "First launch will take ~5-10 min for the Python runtime install."
