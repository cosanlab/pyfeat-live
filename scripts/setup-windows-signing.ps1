# Called after azure/login's OIDC authentication. Never writes private keys.
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$signingDir = Join-Path $env:RUNNER_TEMP 'artifact-signing'
New-Item -ItemType Directory -Force $signingDir | Out-Null
$package = Join-Path $signingDir 'client.zip'
Invoke-WebRequest 'https://www.nuget.org/api/v2/package/Microsoft.ArtifactSigning.Client/1.0.128' -OutFile $package
Expand-Archive -LiteralPath $package -DestinationPath (Join-Path $signingDir 'client') -Force
$dlib = Join-Path $signingDir 'client/bin/x64/Azure.CodeSigning.Dlib.dll'
if (!(Test-Path -LiteralPath $dlib)) { throw 'Artifact Signing x64 dlib is missing.' }

# Avoid the old SDK 20348 SignTool, which is incompatible with the dlib.
$sdkRoot = Join-Path ${env:ProgramFiles(x86)} 'Windows Kits/10/bin'
$sdk = Get-ChildItem -LiteralPath $sdkRoot -Directory |
    Where-Object { $_.Name -match '^10\.0\.\d+\.\d+$' -and [version]$_.Name -ge [version]'10.0.22621.0' } |
    Sort-Object { [version]$_.Name } -Descending |
    Where-Object { Test-Path (Join-Path $_.FullName 'x64/signtool.exe') } |
    Select-Object -First 1
if (!$sdk) { throw 'Install Windows SDK 10.0.22621 or newer (x64 SignTool).' }
$signtool = Join-Path $sdk.FullName 'x64/signtool.exe'

$metadataPath = Join-Path $signingDir 'metadata.json'
@{
    Endpoint = $env:TRUSTED_SIGNING_ENDPOINT
    CodeSigningAccountName = $env:TRUSTED_SIGNING_ACCOUNT
    CertificateProfileName = $env:TRUSTED_SIGNING_PROFILE
    # Reuse azure/login through AzureCliCredential only. The CLI wrapper
    # artifact-signing-cli requires a client secret and cannot do this.
    ExcludeCredentials = @(
        'EnvironmentCredential', 'WorkloadIdentityCredential',
        'ManagedIdentityCredential', 'SharedTokenCacheCredential',
        'VisualStudioCredential', 'VisualStudioCodeCredential',
        'AzurePowerShellCredential', 'AzureDeveloperCliCredential',
        'InteractiveBrowserCredential'
    )
} | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $metadataPath -Encoding utf8

$confPath = Join-Path $env:GITHUB_WORKSPACE 'tauri/src-tauri/tauri.conf.json'
$conf = Get-Content -LiteralPath $confPath -Raw | ConvertFrom-Json -AsHashtable
# Structured arguments preserve spaces in file names and absolute tool paths.
# Tauri invokes this for the app, sidecars, and installers before producing
# updater signatures. Signing an installer AFTER that would invalidate .sig.
$conf.bundle.windows.signCommand = @{
    cmd = $signtool
    args = @('sign', '/fd', 'SHA256', '/tr', 'http://timestamp.acs.microsoft.com',
        '/td', 'SHA256', '/d', 'Py-feat Live', '/dlib', $dlib,
        '/dmdf', $metadataPath, '%1')
}
$conf | ConvertTo-Json -Depth 100 | Set-Content -LiteralPath $confPath -Encoding utf8
Write-Output "Windows signing configured with SDK $($sdk.Name)."
