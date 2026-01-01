$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$repo = Resolve-Path (Join-Path $root "..")

Write-Host "Repo: $repo"
Set-Location $repo

$exeName = "LighthouseLayoutCoach"
$distExe = Join-Path $repo "dist\\$exeName.exe"
if (Test-Path $distExe) {
  # If a previous run is still open, PyInstaller can't overwrite the EXE.
  Get-Process $exeName -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
  Start-Sleep -Milliseconds 300
}

$venv = Join-Path $repo ".venv_build"
if (Test-Path $venv) {
  Remove-Item -Recurse -Force $venv
}

python -m venv $venv
& (Join-Path $venv "Scripts\\Activate.ps1")

python -m pip install --upgrade pip
pip install -r requirements.txt
pip install pyinstaller

# Optional: bundle VC++ runtime installer to reduce "Failed to load Python DLL" issues on fresh machines.
$redistDir = Join-Path $repo "packaging\\redist"
$vcRedist = Join-Path $redistDir "vc_redist.x64.exe"
New-Item -ItemType Directory -Force -Path $redistDir | Out-Null
if (!(Test-Path $vcRedist)) {
  try {
    $url = "https://aka.ms/vs/17/release/vc_redist.x64.exe"
    Write-Host "Downloading VC++ Redistributable (x64): $url"
    Invoke-WebRequest -Uri $url -OutFile $vcRedist -UseBasicParsing
  } catch {
    Write-Host "WARNING: Failed to download VC++ Redistributable; installer will not be able to auto-install it."
  }
}

if (!(Test-Path "packaging\\LighthouseLayoutCoach.spec")) {
  throw "Missing packaging\\LighthouseLayoutCoach.spec"
}

pyinstaller --noconfirm packaging\\LighthouseLayoutCoach.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed with exit code $LASTEXITCODE" }

Write-Host "Built EXE: dist\\LighthouseLayoutCoach.exe"
if (!(Test-Path "dist\\LighthouseLayoutCoach.exe")) { throw "Expected dist\\LighthouseLayoutCoach.exe not found" }

# Read VERSION for installer metadata
$version = (Get-Content -Path (Join-Path $repo "VERSION") -TotalCount 1).Trim()
if (!$version) { $version = "0.0.0" }

# Optional: build installer if Inno Setup compiler is present
$isccCandidates = @(
  "${env:ProgramFiles(x86)}\\Inno Setup 6\\ISCC.exe",
  "${env:ProgramFiles}\\Inno Setup 6\\ISCC.exe"
)
$iscc = $isccCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if ($iscc) {
  New-Item -ItemType Directory -Force -Path "dist\\Installer" | Out-Null
  & $iscc "packaging\\installer.iss" /DMyAppVersion="$version" /O"dist\\Installer"
  if ($LASTEXITCODE -ne 0) { throw "Inno Setup compile failed with exit code $LASTEXITCODE" }
  Write-Host "Built installer: dist\\Installer\\LighthouseLayoutCoach_Setup.exe"
} else {
  Write-Host "Inno Setup not found; skipping installer build. Install Inno Setup 6 to enable."
}

# Release assets folder (only the two binaries for GitHub Releases)
New-Item -ItemType Directory -Force -Path "dist\\release_assets" | Out-Null
Copy-Item -Force "dist\\LighthouseLayoutCoach.exe" "dist\\release_assets\\LighthouseLayoutCoach.exe"
if (Test-Path "dist\\Installer\\LighthouseLayoutCoach_Setup.exe") {
  Copy-Item -Force "dist\\Installer\\LighthouseLayoutCoach_Setup.exe" "dist\\release_assets\\LighthouseLayoutCoach_Setup.exe"
}
Write-Host "Release assets: dist\\release_assets\\LighthouseLayoutCoach.exe"
Write-Host "Release assets: dist\\release_assets\\LighthouseLayoutCoach_Setup.exe"
