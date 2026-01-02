# Unity OpenXR Setup (SteamVR)

These settings are required for controller models and ray UI interaction to work in VR.

## Enable OpenXR for Windows
1) Open Unity project: `unity_vr_coach/`
2) **Edit → Project Settings → XR Plug-in Management**
3) Select **PC, Mac & Linux Standalone**
4) Check **OpenXR**

## Enable controller interaction profiles
1) **Edit → Project Settings → XR Plug-in Management → OpenXR**
2) Under **Interaction Profiles**, enable:
   - **Oculus Touch Controller Profile** (Quest via Virtual Desktop / Link)
   - **Valve Index Controller Profile**
   - (Optional) **HTC Vive Controller Profile**

If these are not enabled, you may see head tracking but **no controllers** and **no ray interaction**.

## Input System
1) **Edit → Project Settings → Player → Active Input Handling**
2) Set to **Input System Package (New)** or **Both**

## Scene checklist
- Open `unity_vr_coach/Assets/Scenes/CoachScene.unity`
- Press Play with SteamVR running
- You should see:
  - Left and right controller models (simple capsules)
  - Visible rays (line) from controllers
  - “Coach Menu” world-space panel at about `(0, 1.3, 1.5)` (not attached to your head)

