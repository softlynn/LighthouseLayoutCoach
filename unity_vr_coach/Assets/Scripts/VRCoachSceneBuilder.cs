using System;
using UnityEngine;
using UnityEngine.EventSystems;
using UnityEngine.UI;
using UnityEngine.XR.Interaction.Toolkit.UI;
using UnityEngine.XR;

// XR Interaction Toolkit types are in separate assemblies; keep usage minimal and guarded.
#if ENABLE_INPUT_SYSTEM
using UnityEngine.InputSystem.UI;
#endif

namespace LighthouseLayoutCoach.VRCoach
{
    public sealed class VRCoachSceneBuilder : MonoBehaviour
    {
        private const float PanelDistance = 1.2f;
        private static Text _statusText;
        private static Text _clickTestText;
        private static int _clickCount;

        private void Start()
        {
            EnsureCamera();
            EnsureWorldSpaceMenu();
        }

        private static void EnsureCamera()
        {
            if (Camera.main != null)
                return;

            var camGo = new GameObject("Main Camera");
            camGo.tag = "MainCamera";
            camGo.transform.position = new Vector3(0, 1.6f, 0);
            camGo.AddComponent<Camera>();
            camGo.AddComponent<AudioListener>();
        }

        private static void EnsureWorldSpaceMenu()
        {
            EnsureEventSystem();

            var canvasGo = new GameObject("Coach Menu");
            var canvas = canvasGo.AddComponent<Canvas>();
            canvas.renderMode = RenderMode.WorldSpace;
            canvas.worldCamera = Camera.main;

            var scaler = canvasGo.AddComponent<CanvasScaler>();
            scaler.uiScaleMode = CanvasScaler.ScaleMode.ConstantPixelSize;
            scaler.scaleFactor = 1f;

            // Prefer XR UI raycaster (required for XR controller ray UI).
            canvasGo.AddComponent<TrackedDeviceGraphicRaycaster>();

            var rect = canvas.GetComponent<RectTransform>();
            rect.sizeDelta = new Vector2(520, 420);

            // Place in front of the playspace (NOT head-locked / not parented to the camera).
            canvasGo.transform.position = new Vector3(0, 1.3f, 1.5f);
            canvasGo.transform.rotation = Quaternion.LookRotation(Vector3.zero - canvasGo.transform.position);
            canvasGo.transform.localScale = Vector3.one * 0.0022f;

            var panel = new GameObject("Panel");
            panel.transform.SetParent(canvasGo.transform, false);
            var panelImage = panel.AddComponent<Image>();
            panelImage.color = new Color(0.08f, 0.09f, 0.11f, 0.92f);
            var panelRect = panel.GetComponent<RectTransform>();
            panelRect.anchorMin = Vector2.zero;
            panelRect.anchorMax = Vector2.one;
            panelRect.offsetMin = new Vector2(0, 0);
            panelRect.offsetMax = new Vector2(0, 0);

            var title = CreateText(panel.transform, "Title", "LighthouseLayoutCoach VR Coach", 22, TextAnchor.UpperLeft);
            var titleRect = title.GetComponent<RectTransform>();
            titleRect.anchorMin = new Vector2(0, 1);
            titleRect.anchorMax = new Vector2(1, 1);
            titleRect.pivot = new Vector2(0.5f, 1);
            titleRect.anchoredPosition = new Vector2(0, -18);
            titleRect.sizeDelta = new Vector2(-24, 40);

            var status = CreateText(panel.transform, "Status", "OpenXR: (pending)\nControllers: (pending)\nUI click test: press button", 14, TextAnchor.UpperLeft);
            _statusText = status.GetComponent<Text>();
            var statusRect = status.GetComponent<RectTransform>();
            statusRect.anchorMin = new Vector2(0, 1);
            statusRect.anchorMax = new Vector2(1, 1);
            statusRect.pivot = new Vector2(0.5f, 1);
            statusRect.anchoredPosition = new Vector2(0, -62);
            statusRect.sizeDelta = new Vector2(-24, 80);

            var togglesRoot = new GameObject("Toggles");
            togglesRoot.transform.SetParent(panel.transform, false);
            var togglesRect = togglesRoot.AddComponent<RectTransform>();
            togglesRect.anchorMin = new Vector2(0, 0);
            togglesRect.anchorMax = new Vector2(1, 1);
            togglesRect.offsetMin = new Vector2(16, 16);
            togglesRect.offsetMax = new Vector2(-16, -150);

            var layout = togglesRoot.AddComponent<VerticalLayoutGroup>();
            layout.spacing = 10;
            layout.childForceExpandHeight = false;
            layout.childForceExpandWidth = true;
            layout.childControlHeight = true;
            layout.childControlWidth = true;

            togglesRoot.AddComponent<ContentSizeFitter>().verticalFit = ContentSizeFitter.FitMode.PreferredSize;

            CreateToggle(togglesRoot.transform, "Show Base Stations", true);
            CreateToggle(togglesRoot.transform, "Show Trackers", true);
            CreateToggle(togglesRoot.transform, "Heatmap On/Off", false);
            CreateToggle(togglesRoot.transform, "Body Placement On/Off", false);
            CreateToggle(togglesRoot.transform, "Use Historical Logs On/Off", true);
            CreateToggle(togglesRoot.transform, "Debug Info On/Off", false);

            var btn = CreateButton(panel.transform, "Click Test", "Click Test");
            var btnRect = btn.GetComponent<RectTransform>();
            btnRect.anchorMin = new Vector2(0, 0);
            btnRect.anchorMax = new Vector2(0, 0);
            btnRect.pivot = new Vector2(0, 0);
            btnRect.anchoredPosition = new Vector2(16, 16);
            btnRect.sizeDelta = new Vector2(200, 44);

            _clickTestText = CreateText(panel.transform, "ClickTestStatus", "Clicks: 0", 14, TextAnchor.MiddleLeft).GetComponent<Text>();
            var ctRect = _clickTestText.GetComponent<RectTransform>();
            ctRect.anchorMin = new Vector2(0, 0);
            ctRect.anchorMax = new Vector2(1, 0);
            ctRect.pivot = new Vector2(0, 0);
            ctRect.anchoredPosition = new Vector2(230, 20);
            ctRect.sizeDelta = new Vector2(-246, 30);
        }

        private static void EnsureEventSystem()
        {
            if (FindObjectOfType<EventSystem>() != null)
                return;

            var es = new GameObject("EventSystem");
            es.AddComponent<EventSystem>();

#if ENABLE_INPUT_SYSTEM
            es.AddComponent<XRUIInputModule>();
#else
            es.AddComponent<StandaloneInputModule>();
#endif
        }

        private static GameObject CreateText(Transform parent, string name, string text, int fontSize, TextAnchor align)
        {
            var go = new GameObject(name);
            go.transform.SetParent(parent, false);
            var t = go.AddComponent<Text>();
            t.text = text;
            t.fontSize = fontSize;
            t.alignment = align;
            t.color = new Color(0.92f, 0.92f, 0.92f, 1f);
            t.horizontalOverflow = HorizontalWrapMode.Wrap;
            t.verticalOverflow = VerticalWrapMode.Overflow;
            t.font = Resources.GetBuiltinResource<Font>("Arial.ttf");
            var rect = t.GetComponent<RectTransform>();
            rect.sizeDelta = new Vector2(480, 40);
            rect.anchoredPosition = Vector2.zero;
            return go;
        }

        private static GameObject CreateButton(Transform parent, string name, string label)
        {
            var go = new GameObject(name);
            go.transform.SetParent(parent, false);
            var img = go.AddComponent<Image>();
            img.color = new Color(0.15f, 0.17f, 0.22f, 0.98f);

            var btn = go.AddComponent<Button>();
            btn.onClick.AddListener(() =>
            {
                _clickCount++;
                if (_clickTestText != null)
                    _clickTestText.text = $"Clicks: {_clickCount}";
            });

            var text = CreateText(go.transform, "Label", label, 14, TextAnchor.MiddleCenter);
            var tr = text.GetComponent<RectTransform>();
            tr.anchorMin = Vector2.zero;
            tr.anchorMax = Vector2.one;
            tr.offsetMin = Vector2.zero;
            tr.offsetMax = Vector2.zero;
            return go;
        }

        private void Update()
        {
            if (_statusText == null)
                return;

            var xrActive = XRSettings.isDeviceActive;
            var left = InputDevices.GetDeviceAtXRNode(XRNode.LeftHand);
            var right = InputDevices.GetDeviceAtXRNode(XRNode.RightHand);
            _statusText.text =
                $"OpenXR/XR active: {(xrActive ? "YES" : "NO")}\nControllers: L={(left.isValid ? "YES" : "NO")} R={(right.isValid ? "YES" : "NO")}\nUI click test: press button";
        }

        private static void CreateToggle(Transform parent, string label, bool defaultValue)
        {
            var row = new GameObject(label);
            row.transform.SetParent(parent, false);
            var rowRect = row.AddComponent<RectTransform>();
            rowRect.sizeDelta = new Vector2(0, 44);

            var bg = new GameObject("Background");
            bg.transform.SetParent(row.transform, false);
            var bgImage = bg.AddComponent<Image>();
            bgImage.color = new Color(0.12f, 0.13f, 0.16f, 0.95f);
            var bgRect = bg.GetComponent<RectTransform>();
            bgRect.anchorMin = Vector2.zero;
            bgRect.anchorMax = Vector2.one;
            bgRect.offsetMin = Vector2.zero;
            bgRect.offsetMax = Vector2.zero;

            var toggleGo = new GameObject("Toggle");
            toggleGo.transform.SetParent(row.transform, false);
            var toggle = toggleGo.AddComponent<Toggle>();

            var toggleRect = toggleGo.GetComponent<RectTransform>();
            toggleRect.anchorMin = new Vector2(0, 0.5f);
            toggleRect.anchorMax = new Vector2(0, 0.5f);
            toggleRect.pivot = new Vector2(0, 0.5f);
            toggleRect.anchoredPosition = new Vector2(12, 0);
            toggleRect.sizeDelta = new Vector2(26, 26);

            var checkBg = new GameObject("CheckBg");
            checkBg.transform.SetParent(toggleGo.transform, false);
            var checkBgImage = checkBg.AddComponent<Image>();
            checkBgImage.color = new Color(0.18f, 0.18f, 0.18f, 1f);
            var checkBgRect = checkBg.GetComponent<RectTransform>();
            checkBgRect.anchorMin = Vector2.zero;
            checkBgRect.anchorMax = Vector2.one;
            checkBgRect.offsetMin = Vector2.zero;
            checkBgRect.offsetMax = Vector2.zero;

            var checkmark = new GameObject("Checkmark");
            checkmark.transform.SetParent(checkBg.transform, false);
            var checkmarkImage = checkmark.AddComponent<Image>();
            checkmarkImage.color = new Color(0.23f, 0.85f, 0.58f, 1f);
            var checkRect = checkmark.GetComponent<RectTransform>();
            checkRect.anchorMin = new Vector2(0.2f, 0.2f);
            checkRect.anchorMax = new Vector2(0.8f, 0.8f);
            checkRect.offsetMin = Vector2.zero;
            checkRect.offsetMax = Vector2.zero;

            toggle.targetGraphic = checkBgImage;
            toggle.graphic = checkmarkImage;
            toggle.isOn = defaultValue;

            var text = CreateText(row.transform, "Label", label, 14, TextAnchor.MiddleLeft);
            var textRect = text.GetComponent<RectTransform>();
            textRect.anchorMin = new Vector2(0, 0);
            textRect.anchorMax = new Vector2(1, 1);
            textRect.offsetMin = new Vector2(52, 0);
            textRect.offsetMax = new Vector2(-12, 0);
        }
    }
}
