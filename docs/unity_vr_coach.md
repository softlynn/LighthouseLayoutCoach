# Unity VR Coach (Unity-only)

## Requirements
- Unity **2022.3 LTS** (tested: `2022.3.62f3`)
- Windows PC + SteamVR runtime
- Unity packages are declared in `unity_vr_coach/Packages/manifest.json`

## Open the project
1) Open Unity Hub → Add project → select `unity_vr_coach/`.
2) Let Unity import packages.
3) Open `Assets/Scenes/CoachScene.unity`.

## Enable OpenXR (one-time)
1) Edit → Project Settings → XR Plug-in Management
2) PC, Mac & Linux Standalone → enable **OpenXR**
3) OpenXR → Interaction Profiles: enable common controller profiles you use (e.g. Valve Index, Oculus Touch).

## Run in VR
1) Start SteamVR.
2) In Unity, press Play. You should see a world-space “Coach Menu” panel (not head-locked).

## Build (Windows)
Preferred (scripted):
- `powershell -ExecutionPolicy Bypass -File scripts/build_unity_vr_coach.ps1`

Manual:
1) File → Build Settings
2) Platform: PC, Mac & Linux Standalone → Target Platform: Windows
3) Ensure `CoachScene` is in Scenes In Build
4) Build to `releases/VRCoach_Windows/` as `LighthouseLayoutCoachVRCoach.exe`

## Launch from the Desktop app
The desktop launcher has a `Launch VR Coach (Unity)` button.

- Installed app: place the Unity build at `VRCoach/` next to `LighthouseLayoutCoach.exe`:
  - `VRCoach/LighthouseLayoutCoachVRCoach.exe`
  - `VRCoach/LighthouseLayoutCoachVRCoach_Data/`
- Source checkout: place the build at:
  - `releases/VRCoach_Windows/LighthouseLayoutCoachVRCoach.exe`

