using System;
using UnityEditor;
using UnityEngine;

namespace LighthouseLayoutCoach.VRCoach.Editor
{
    [InitializeOnLoad]
    public static class AutoConfigureXR
    {
        private const string Key = "LLC_VRCoach_AutoConfigured";

        static AutoConfigureXR()
        {
            EditorApplication.delayCall += RunOnce;
        }

        private static void RunOnce()
        {
            if (EditorPrefs.GetBool(Key, false))
                return;

            try
            {
                // Prefer Input System; XRIT uses it for UI and controller input.
                var current = PlayerSettings.GetScriptingDefineSymbolsForGroup(BuildTargetGroup.Standalone);
                if (!current.Contains("ENABLE_INPUT_SYSTEM"))
                {
                    PlayerSettings.SetScriptingDefineSymbolsForGroup(BuildTargetGroup.Standalone, current);
                }
            }
            catch (Exception e)
            {
                Debug.LogWarning($"VRCoach auto-config: {e.GetType().Name}: {e.Message}");
            }
            finally
            {
                EditorPrefs.SetBool(Key, true);
                Debug.Log("VRCoach: opened project. Next: Project Settings → XR Plug-in Management → enable OpenXR (Windows).");
            }
        }
    }
}

