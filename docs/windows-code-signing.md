# Windows builds and code signing

Windows x86_64 produces NSIS (`-setup.exe`) and MSI installers. The
`Windows build` workflow builds both on pull requests without credentials and
uploads them as test artifacts. The release workflow also signs updater
artifacts with the existing Tauri key. That key does not establish a Windows
publisher identity: Windows uses a separate Authenticode signature.

## Azure prerequisites

The Azure account is **pyfeatlivesigning**, in **East US**, with endpoint
`https://eus.codesigning.azure.net/`. The Public Trust certificate profile is
**pyfeat-live**, and the CI app registration is **pyfeat-live-github-signing**.
It uses Azure **Artifact Signing**
(previously Trusted Signing), not an Apple Developer certificate or a Microsoft
Store submission certificate.

CI cannot produce a publicly trusted signature until identity validation
completes and a Public Trust profile exists. Leave signing disabled until
these prerequisites and the GitHub settings below are ready.

In the Azure portal, open the account, then **Identity validations**, switch
**Organizations → Individuals**, and inspect the request. Review the updated
terms. Follow [Microsoft's individual validation instructions](https://learn.microsoft.com/en-us/azure/artifact-signing/quickstart)
to submit a new request if the previous verification expired or the details
need correction. The legal name and address must match the accepted identity
documents and Azure billing account. Use the same Microsoft account email when
opening the verification link. Complete the phone/Authenticator identity checks
yourself; never put identity documents, verification links, or private keys in
GitHub issues or secrets.

If a fresh request fails, use Azure Support with the request ID. Microsoft's
[validation FAQ](https://learn.microsoft.com/en-us/azure/artifact-signing/faq)
explains email expiration and identity verification troubleshooting. A failed
status alone does not prove the cause was an expired link.

## Enable signing after validation

1. Create a **Public Trust** certificate profile in `pyfeatlivesigning` using
   the completed individual identity. Do not use Public Trust Test or Private
   Trust for installers distributed to the public.
2. Create an Entra app registration for GitHub Actions. Record its application
   (client) ID and directory (tenant) ID.
3. Add a federated credential for GitHub Actions:
   - Organization: `cosanlab`
   - Repository: `pyfeat-live`
   - Entity: **Environment**
   - Environment name: `windows-signing`
   - Issuer: `https://token.actions.githubusercontent.com`
   - Subject: `repo:cosanlab/pyfeat-live:environment:windows-signing`
   - Audience: `api://AzureADTokenExchange`
   Check the repository's OIDC subject configuration before saving. Azure may
   generate a subject containing organization/repository IDs, but this
   repository currently uses the name-based subject above. Use **Edit** beside
   the generated subject to match GitHub's actual token.
4. Grant that app **Artifact Signing Certificate Profile Signer** at the
   certificate profile scope (the portal may retain the old Trusted Signing
   role name). Subscription Contributor/Owner is not the signing permission.
5. Create the GitHub environment **windows-signing**. Restrict deployment refs
   to release tags (`v*`); protect tag creation and optionally require review.
   If manually dispatching a release, select its tag as the workflow ref too.
6. Add these settings to that environment:

   | Kind | Name | Value |
   | --- | --- | --- |
   | Secret | `AZURE_CLIENT_ID` | App registration client ID |
   | Secret | `AZURE_TENANT_ID` | Directory tenant ID |
   | Variable | `TRUSTED_SIGNING_ENDPOINT` | `https://eus.codesigning.azure.net/` |
   | Variable | `TRUSTED_SIGNING_ACCOUNT` | `pyfeatlivesigning` |
   | Variable | `TRUSTED_SIGNING_PROFILE` | `pyfeat-live` |
   | Variable | `WINDOWS_SIGNING_ENABLED` | `true` |

No client secret or downloadable PFX is needed. The release job requests an
OIDC token using `id-token: write`; `azure/login` establishes the Azure CLI
session. SignTool's Artifact Signing dlib uses **AzureCliCredential** from that
session. `artifact-signing-cli` is intentionally not used: it requires a client
secret and performs its own login.

The macOS matrix job uses `macos-release`; its existing repository secrets still
apply. It does not use the Windows environment's credentials.

## Signing order and checks

`scripts/setup-windows-signing.ps1` installs the pinned Microsoft signing dlib,
selects a compatible x64 Windows SDK SignTool, writes non-secret metadata in the
runner temp directory, and injects a structured `bundle.windows.signCommand`.
This CI-only config leaves local builds independent of Azure.

Tauri invokes SignTool while packaging the app, sidecars that need signing,
and installers. Existing valid third-party signatures may be retained. The
command uses SHA-256 and Microsoft's RFC 3161 timestamp service. The Tauri
updater `.sig` is created after Authenticode signing; never modify or re-sign
the installer after that without regenerating its updater signature.

The release job verifies the vendor uv binary, NSIS installer, and MSI have valid,
timestamped signatures before the updater manifest job can run. The raw app EXE
in `target/release` is not checked: Tauri restores it after packaging, so it is
not the signed copy inside the installer. Assets uploaded
by tauri-action stay in a draft release; review the run before publishing.

With `WINDOWS_SIGNING_ENABLED=true`, missing configuration or signing failure
fails the job. Unset/`false` explicitly retains the interim unsigned build and
emits a warning. Enabling signing does not remove the separate
`TAURI_SIGNING_PRIVATE_KEY` requirement for automatic updates.

On Windows, check a downloaded installer:

```powershell
Get-AuthenticodeSignature '.\Py-feat Live_setup.exe' | Format-List
```

Expect `Status: Valid`, the intended publisher in `SignerCertificate`, and a
`TimeStamperCertificate`. Signed apps can still show a SmartScreen reputation
warning; that differs from an unsigned installer's unknown publisher warning.

References: [Microsoft signing integration](https://learn.microsoft.com/en-us/azure/artifact-signing/how-to-signing-integrations),
[Tauri Windows signing](https://v2.tauri.app/distribute/sign/windows/).
