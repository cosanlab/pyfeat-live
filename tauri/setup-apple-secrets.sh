#!/bin/bash
# Push the Apple Developer + Tauri signing secrets to the GitHub repo.
#
# Run AFTER the Apple-side setup is done:
#   1. Developer ID Application certificate installed in Keychain Access
#      (`security find-identity -v -p codesigning` shows it)
#   2. App Store Connect API key downloaded (.p8 file)
#   3. Tauri signing keypair generated (or this script will create one)
#
# The script does:
#   - Verifies the cert is installed and prints the exact signing identity
#   - Walks you through .p12 export (interactive — Keychain Access GUI)
#   - Generates the Tauri updater keypair if missing
#   - Pushes 7 secrets to cosanlab/pyfeat-live via `gh secret set`
#
# It does NOT modify tauri.conf.json — copy-paste the public key into
# `plugins.updater.pubkey` yourself when prompted.

set -euo pipefail

REPO="${REPO:-cosanlab/pyfeat-live}"
TAURI_KEY_DIR="${TAURI_KEY_DIR:-$HOME/.tauri}"
TAURI_KEY="${TAURI_KEY_DIR}/pyfeatlive.key"
SCRATCH=$(mktemp -d)
trap 'rm -rf "$SCRATCH"' EXIT

echo "==> Repository: $REPO"
echo "==> Scratch dir (auto-cleaned): $SCRATCH"
echo

# ----------------------------------------------------------------------
# 0. sanity: gh CLI authed
# ----------------------------------------------------------------------
if ! gh auth status &>/dev/null; then
    echo "ERROR: gh CLI not authenticated. Run: gh auth login" >&2
    exit 1
fi

# ----------------------------------------------------------------------
# 1. find the Developer ID Application identity
# ----------------------------------------------------------------------
echo "==> Looking for Developer ID Application certificate..."
identity=$(security find-identity -v -p codesigning 2>/dev/null \
    | grep "Developer ID Application:" \
    | head -1 \
    | sed -E 's/^[[:space:]]*[0-9]+\)[[:space:]]+[0-9A-F]+[[:space:]]+"(.*)"$/\1/')

if [ -z "$identity" ]; then
    echo "ERROR: no Developer ID Application certificate in Keychain." >&2
    echo "       Create one at https://developer.apple.com/account/resources/certificates/list" >&2
    echo "       (see tauri/UPDATER.md for the full walkthrough)" >&2
    exit 1
fi
echo "    Found: $identity"

# Extract Team ID from the identity name "Developer ID Application: Name (TEAMID)"
team_id=$(echo "$identity" | sed -E 's/.*\(([0-9A-Z]{10})\)$/\1/')
if [ ${#team_id} -ne 10 ]; then
    echo "WARN: could not auto-extract Team ID from identity name." >&2
    read -r -p "    Enter your 10-char Team ID manually: " team_id
fi
echo "    Team ID: $team_id"
echo

# ----------------------------------------------------------------------
# 2. .p12 file path — interactive
# ----------------------------------------------------------------------
echo "==> Developer ID certificate (.p12)"
echo
echo "    Export the cert from Keychain Access:"
echo "      - Switch to the 'My Certificates' tab (.p12 only enables there)"
echo "      - Right-click '$identity'"
echo "      - Export… → File Format: Personal Information Exchange (.p12)"
echo "      - Save it anywhere; set a password (you'll paste it below)"
echo
read -r -p "    Path to your .p12 file: " p12_path
p12_path="${p12_path/#\~/$HOME}"
if [ ! -f "$p12_path" ]; then
    echo "ERROR: $p12_path not found." >&2
    exit 1
fi
echo "    .p12 found ($(stat -f%z "$p12_path") bytes)"

read -r -s -p "    Password you set on the .p12 export: " p12_password
echo

# ----------------------------------------------------------------------
# 3. App Store Connect API key
# ----------------------------------------------------------------------
echo
echo "==> App Store Connect API credentials"
read -r -p "    Path to your AuthKey_*.p8 file: " p8_path
p8_path="${p8_path/#\~/$HOME}"
if [ ! -f "$p8_path" ]; then
    echo "ERROR: $p8_path not found." >&2
    exit 1
fi
read -r -p "    Key ID (10 chars from App Store Connect): " api_key_id
read -r -p "    Issuer ID (UUID from App Store Connect): " api_issuer
echo

# ----------------------------------------------------------------------
# 4. Tauri updater keypair
# ----------------------------------------------------------------------
echo "==> Tauri updater signing keypair"
if [ ! -f "$TAURI_KEY" ]; then
    echo "    No existing keypair at $TAURI_KEY — generating now."
    mkdir -p "$TAURI_KEY_DIR"
    pushd "$(dirname "$0")" >/dev/null
    ./node_modules/.bin/tauri signer generate -w "$TAURI_KEY"
    popd >/dev/null
else
    echo "    Reusing existing keypair at $TAURI_KEY"
fi

if [ ! -f "${TAURI_KEY}.pub" ]; then
    echo "ERROR: public key ${TAURI_KEY}.pub not found." >&2
    exit 1
fi

read -r -s -p "    Password you used for the Tauri keypair: " tauri_password
echo
echo

# ----------------------------------------------------------------------
# 5. push secrets to GHA
# ----------------------------------------------------------------------
push() {
    local name="$1" value="$2"
    printf '    %-40s ' "$name"
    if echo -n "$value" | gh secret set "$name" --repo "$REPO" --body - >/dev/null; then
        echo "ok"
    else
        echo "FAIL" >&2
        return 1
    fi
}

echo "==> Pushing secrets to $REPO ..."
# Naming follows tauri-action's expected env vars exactly:
#   APPLE_API_KEY         = the 10-char Key ID (string)
#   APPLE_API_ISSUER      = the issuer UUID
#   APPLE_API_KEY_PATH    = filesystem path to the .p8 (set in the
#                           workflow from APPLE_API_KEY_BASE64)
push APPLE_CERTIFICATE                  "$(base64 < "$p12_path" | tr -d '\n')"
push APPLE_CERTIFICATE_PASSWORD         "$p12_password"
push APPLE_SIGNING_IDENTITY             "$identity"
push APPLE_TEAM_ID                      "$team_id"
push APPLE_API_KEY                      "$api_key_id"
push APPLE_API_ISSUER                   "$api_issuer"
push APPLE_API_KEY_BASE64               "$(base64 < "$p8_path" | tr -d '\n')"
push TAURI_SIGNING_PRIVATE_KEY          "$(base64 < "$TAURI_KEY" | tr -d '\n')"
push TAURI_SIGNING_PRIVATE_KEY_PASSWORD "$tauri_password"

echo
echo "==> Done."
echo
echo "    Next step: paste the Tauri public key into tauri.conf.json"
echo "    The pubkey is at:"
echo "        $TAURI_KEY.pub"
echo
echo "    Open it and copy the line — paste it as the value of"
echo "        plugins.updater.pubkey  in tauri/src-tauri/tauri.conf.json"
echo
echo "    (currently set to: REPLACE_WITH_BASE64_PUBKEY_FROM_tauri_signer_generate)"
