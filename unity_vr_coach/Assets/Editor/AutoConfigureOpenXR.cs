using System;
using System.Reflection;
using UnityEditor;
using UnityEngine;

namespace LighthouseLayoutCoach.VRCoach.Editor
{
    [InitializeOnLoad]
    public static class AutoConfigureOpenXR
    {
        private const string Key = "LLC_VRCoach_OpenXR_Configured";

        static AutoConfigureOpenXR()
        {
            EditorApplication.delayCall += RunOnce;
        }

        private static void RunOnce()
        {
            if (EditorPrefs.GetBool(Key, false))
                return;

            try
            {
                EnsureInputSystem();
                TryEnableOpenXRForStandalone();
            }
            catch (Exception e)
            {
                Debug.LogWarning($"VRCoach OpenXR auto-config failed: {e.GetType().Name}: {e.Message}");
            }
            finally
            {
                EditorPrefs.SetBool(Key, true);
            }
        }

        private static void EnsureInputSystem()
        {
            // Prefer Input System or Both.
            try
            {
                var playerSettingsType = typeof(PlayerSettings);
                var activeInputHandlingProp = playerSettingsType.GetProperty("activeInputHandler", BindingFlags.Static | BindingFlags.NonPublic);
                if (activeInputHandlingProp == null)
                    return;

                // 0 = old, 1 = new, 2 = both (Unity internal)
                var current = (int)activeInputHandlingProp.GetValue(null);
                if (current == 1 || current == 2)
                    return;

                activeInputHandlingProp.SetValue(null, 2);
                Debug.Log("VRCoach: set Active Input Handling to Both (required for OpenXR/XRIT input).");
            }
            catch
            {
                // ignore
            }
        }

        private static void TryEnableOpenXRForStandalone()
        {
            // Enable OpenXR via XR Plug-in Management editor API (best-effort).
            // Uses reflection to avoid hard assembly ties if packages change.
            var btg = BuildTargetGroup.Standalone;

            var xrGeneralSettingsPerBuildTargetType =
                Type.GetType("UnityEditor.XR.Management.XRGeneralSettingsPerBuildTarget, Unity.XR.Management.Editor");
            var xrPackageMetadataStoreType =
                Type.GetType("UnityEditor.XR.Management.Metadata.XRPackageMetadataStore, Unity.XR.Management.Editor");
            if (xrGeneralSettingsPerBuildTargetType == null || xrPackageMetadataStoreType == null)
            {
                Debug.LogWarning("VRCoach: XR Plug-in Management editor APIs not found. Enable OpenXR manually (see docs/unity_openxr_setup.md).");
                return;
            }

            var xrGeneralSettingsForBuildTarget =
                xrGeneralSettingsPerBuildTargetType.GetMethod("XRGeneralSettingsForBuildTarget", BindingFlags.Static | BindingFlags.Public);
            if (xrGeneralSettingsForBuildTarget == null)
                return;

            var generalSettings = xrGeneralSettingsForBuildTarget.Invoke(null, new object[] { btg });
            if (generalSettings == null)
            {
                Debug.LogWarning("VRCoach: XRGeneralSettings not initialized. Open Project Settings → XR Plug-in Management and enable OpenXR once.");
                return;
            }

            var managerProp = generalSettings.GetType().GetProperty("Manager", BindingFlags.Instance | BindingFlags.Public);
            var manager = managerProp?.GetValue(generalSettings);
            if (manager == null)
                return;

            // XRPackageMetadataStore.AssignLoader(XRManagerSettings, string loaderType, BuildTargetGroup)
            var assignLoader = xrPackageMetadataStoreType.GetMethod(
                "AssignLoader",
                BindingFlags.Static | BindingFlags.Public,
                null,
                new[] { manager.GetType(), typeof(string), typeof(BuildTargetGroup) },
                null
            );
            if (assignLoader == null)
            {
                Debug.LogWarning("VRCoach: AssignLoader API not found. Enable OpenXR manually (see docs/unity_openxr_setup.md).");
                return;
            }

            var loaderType = "UnityEngine.XR.OpenXR.OpenXRLoader";
            var ok = (bool)assignLoader.Invoke(null, new object[] { manager, loaderType, btg });
            if (ok)
            {
                AssetDatabase.SaveAssets();
                Debug.Log("VRCoach: enabled OpenXR for Standalone (PC).");
            }
            else
            {
                Debug.LogWarning("VRCoach: failed to enable OpenXR automatically. Enable it manually (see docs/unity_openxr_setup.md).");
            }
        }
    }
}

