# Unity VR Coach (Unity-only)

## Requirements
- Unity **2022.3 LTS** (recommended: `2022.3.20f1`)
- Windows PC + SteamVR runtime
- Unity packages are declared in `unity_vr_coach/Packages/manifest.json`

## Open the project
1) Open Unity Hub → Add project → select `unity_vr_coach/`.
2) Let Unity import packages.
3) Open `Assets/Scenes/CoachScene.unity`.

## Enable OpenXR (one-time)
1) Project Settings → XR Plug-in Management
2) Standalone → enable **OpenXR**
3) OpenXR → Interaction Profiles: enable common controller profiles you use (e.g. Valve Index, Oculus Touch).

## Run in VR
1) Start SteamVR.
2) In Unity, press Play. You should see a world-space “Coach Menu” panel in front of the camera.
3) If you don’t see the panel, open `Assets/Scenes/CoachScene.unity` and ensure the `CoachBootstrap` object exists.

## Build (Windows)
1) File → Build Settings
2) Platform: PC, Mac & Linux Standalone → Target Platform: Windows
3) Add `CoachScene` to Scenes In Build
4) Build output folder:
   - `releases/VRCoach_Windows/`
5) Name the executable:
   - `LighthouseLayoutCoachVRCoach.exe`

## Launch from the Desktop app
The desktop launcher has a `Launch VR Coach (Unity)` button.

- Installed app: put the Unity build at `VRCoach/` next to `LighthouseLayoutCoach.exe`:
  - `VRCoach/LighthouseLayoutCoachVRCoach.exe`
  - `VRCoach/LighthouseLayoutCoachVRCoach_Data/` (Unity data folder)
- Source checkout: put the build at:
  - `releases/VRCoach_Windows/LighthouseLayoutCoachVRCoach.exe`

## Next steps
Step 2+ (log ingestion, playspace bounds, device visualization) will be implemented incrementally.
