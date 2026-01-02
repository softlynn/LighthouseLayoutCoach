$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$repo = Resolve-Path (Join-Path $root "..")
Set-Location $repo

$projectPath = Join-Path $repo "unity_vr_coach"
if (!(Test-Path $projectPath)) { throw "Missing Unity project: $projectPath" }

function Find-UnityEditorExe {
  param([string]$version)

  $candidates = @()

  $secondary = Join-Path $env:AppData "UnityHub\\secondaryInstallPath.json"
  if (Test-Path $secondary) {
    try {
      $base = (Get-Content $secondary -Raw).Trim().Trim('"')
      if ($base) {
        $candidates += (Join-Path $base "$version\\Editor\\Unity.exe")
      }
    } catch {}
  }

  $candidates += @(
    "$env:ProgramFiles\\Unity\\Hub\\Editor\\$version\\Editor\\Unity.exe",
    "$env:ProgramFiles(x86)\\Unity\\Hub\\Editor\\$version\\Editor\\Unity.exe"
  )

  $candidates | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
}

$unityVersion = "2022.3.62f3"
$unityExe = Find-UnityEditorExe -version $unityVersion
if (!$unityExe) {
  throw "Unity Editor not found for $unityVersion. Set it up in Unity Hub or edit scripts/build_unity_vr_coach.ps1."
}

$outDir = Join-Path $repo "releases\\VRCoach_Windows"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null

$logFile = Join-Path $outDir "unity_build.log"
if (Test-Path $logFile) { Remove-Item -Force $logFile }

Write-Host "Unity: $unityExe"
Write-Host "Project: $projectPath"
Write-Host "Output: $outDir"

$args = @(
  "-batchmode",
  "-quit",
  "-nographics",
  "-projectPath", "$projectPath",
  "-executeMethod", "LighthouseLayoutCoach.VRCoach.Editor.BuildVRCoach.BuildWindows64",
  "-logFile", "$logFile"
)

$proc = Start-Process -FilePath $unityExe -ArgumentList $args -NoNewWindow -Wait -PassThru
if ($proc.ExitCode -ne 0) {
  Write-Host "Unity build log: $logFile"
  throw "Unity build failed with exit code $($proc.ExitCode)"
}

$exe = Join-Path $outDir "LighthouseLayoutCoachVRCoach.exe"
if (!(Test-Path $exe)) { throw "Expected build output missing: $exe" }

Write-Host "Built VR Coach: $exe"
