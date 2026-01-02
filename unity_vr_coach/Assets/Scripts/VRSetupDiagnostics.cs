using System.Collections.Generic;
using UnityEngine;
using UnityEngine.XR;
using UnityEngine.XR.Interaction.Toolkit;
using UnityEngine.XR.Management;

namespace LighthouseLayoutCoach.VRCoach
{
    public sealed class VRSetupDiagnostics : MonoBehaviour
    {
        private float _nextLogTime;
        private string _lastSummary = "";

        private void Start()
        {
            LogOnce();
        }

        private void Update()
        {
            if (Time.unscaledTime < _nextLogTime)
                return;
            _nextLogTime = Time.unscaledTime + 1f;
            LogOnce();
        }

        private void LogOnce()
        {
            var xrOk = XRSettings.isDeviceActive;
            var loader = XRGeneralSettings.Instance != null ? XRGeneralSettings.Instance.Manager.activeLoader : null;
            var loaderName = loader != null ? loader.name : "(none)";

            var displayRunning = false;
            var displays = new List<XRDisplaySubsystem>();
            SubsystemManager.GetInstances(displays);
            foreach (var d in displays)
                displayRunning |= d.running;

            var left = InputDevices.GetDeviceAtXRNode(XRNode.LeftHand);
            var right = InputDevices.GetDeviceAtXRNode(XRNode.RightHand);

            var hasRay = FindObjectOfType<XRRayInteractor>() != null;

            var summary = $"OpenXR loader: {loaderName} | XR active: {xrOk} | display running: {displayRunning} | left: {left.isValid} right: {right.isValid} | ray: {hasRay}";
            if (summary != _lastSummary)
            {
                Debug.Log("VRSetupDiagnostics: " + summary);
                _lastSummary = summary;
            }
        }
    }
}

