using System;
using System.Reflection;
using UnityEngine;
using UnityEngine.EventSystems;
using UnityEngine.InputSystem;
using UnityEngine.InputSystem.UI;
using UnityEngine.XR;
using UnityEngine.XR.Interaction.Toolkit;
using UnityEngine.XR.Interaction.Toolkit.UI;
using Unity.XR.CoreUtils;

namespace LighthouseLayoutCoach.VRCoach
{
    public sealed class XRCoachRigBootstrap : MonoBehaviour
    {
        private InputAction _rightPos;
        private InputAction _rightRot;
        private InputAction _rightSelect;
        private InputAction _rightUIPress;
        private InputAction _rightUIScroll;

        private void Start()
        {
            EnsureXRInteractionManager();
            EnsureXROriginActionBased();
            EnsureEventSystemXrUi();
        }

        private static void EnsureXRInteractionManager()
        {
            if (FindObjectOfType<XRInteractionManager>() != null)
                return;

            var go = new GameObject("XR Interaction Manager");
            go.AddComponent<XRInteractionManager>();
        }

        private void EnsureXROriginActionBased()
        {
            if (FindObjectOfType<XROrigin>() != null)
                return;

            var originGo = new GameObject("XR Origin (Action-based)");
            var origin = originGo.AddComponent<XROrigin>();
            originGo.AddComponent<CharacterController>();

            var cameraOffset = new GameObject("Camera Offset");
            cameraOffset.transform.SetParent(originGo.transform, false);

            var camGo = new GameObject("Main Camera");
            camGo.tag = "MainCamera";
            camGo.transform.SetParent(cameraOffset.transform, false);
            camGo.AddComponent<Camera>();
            camGo.AddComponent<AudioListener>();

            // Best-effort tracked pose driver (Input System XR).
            TryAddTrackedPoseDriver(camGo);

            origin.CameraFloorOffsetObject = cameraOffset;
            origin.Camera = camGo.GetComponent<Camera>();

            // Simple floor so the user has a reference.
            var floor = GameObject.CreatePrimitive(PrimitiveType.Plane);
            floor.name = "Floor";
            floor.transform.position = Vector3.zero;
            floor.transform.localScale = new Vector3(0.3f, 1f, 0.3f);
            var floorMr = floor.GetComponent<MeshRenderer>();
            floorMr.material = new Material(Shader.Find("Standard"));
            floorMr.material.color = new Color(0.06f, 0.06f, 0.07f, 1f);

            // Controllers
            var left = CreateController(cameraOffset.transform, "Left Controller", XRNode.LeftHand, isLeft: true);
            var right = CreateController(cameraOffset.transform, "Right Controller", XRNode.RightHand, isLeft: false);

            left.transform.localPosition = new Vector3(-0.2f, -0.2f, 0.4f);
            right.transform.localPosition = new Vector3(0.2f, -0.2f, 0.4f);
        }

        private static void TryAddTrackedPoseDriver(GameObject cameraGo)
        {
            try
            {
                // UnityEngine.InputSystem.XR.TrackedPoseDriver
                var t = Type.GetType("UnityEngine.InputSystem.XR.TrackedPoseDriver, Unity.InputSystem");
                if (t == null)
                    return;
                if (cameraGo.GetComponent(t) != null)
                    return;
                cameraGo.AddComponent(t);
            }
            catch
            {
                // ignore
            }
        }

        private GameObject CreateController(Transform parent, string name, XRNode node, bool isLeft)
        {
            var go = new GameObject(name);
            go.transform.SetParent(parent, false);

            // Action-based controller drives transform.
            var controller = go.AddComponent<ActionBasedController>();
            controller.updateTrackingType = ActionBasedController.UpdateType.UpdateAndBeforeRender;

            var hand = isLeft ? "{LeftHand}" : "{RightHand}";

            var positionAction = new InputAction($"{name}/Position", InputActionType.Value, $"<XRController>{hand}/devicePosition");
            var rotationAction = new InputAction($"{name}/Rotation", InputActionType.Value, $"<XRController>{hand}/deviceRotation");
            var selectAction = new InputAction($"{name}/Select", InputActionType.Button, $"<XRController>{hand}/triggerPressed");
            var uiPressAction = new InputAction($"{name}/UIPress", InputActionType.Button, $"<XRController>{hand}/triggerPressed");

            positionAction.Enable();
            rotationAction.Enable();
            selectAction.Enable();
            uiPressAction.Enable();

            controller.positionAction = new InputActionProperty(positionAction);
            controller.rotationAction = new InputActionProperty(rotationAction);
            controller.selectAction = new InputActionProperty(selectAction);
            controller.uiPressAction = new InputActionProperty(uiPressAction);

            // Ray interactor + visible line
            var ray = go.AddComponent<XRRayInteractor>();
            ray.enableUIInteraction = true;
            ray.maxRaycastDistance = 8f;

            var line = go.AddComponent<XRInteractorLineVisual>();
            line.lineWidth = 0.01f;

            var lr = go.AddComponent<LineRenderer>();
            lr.useWorldSpace = false;
            lr.positionCount = 2;
            lr.startWidth = 0.01f;
            lr.endWidth = 0.002f;
            lr.material = new Material(Shader.Find("Sprites/Default"));
            lr.startColor = isLeft ? new Color(0.3f, 0.8f, 1f, 0.9f) : new Color(1f, 0.6f, 0.2f, 0.9f);
            lr.endColor = new Color(lr.startColor.r, lr.startColor.g, lr.startColor.b, 0.1f);

            // XRInteractorLineVisual will pick up the LineRenderer automatically (it looks for one on the same GO).
            line.enabledColorGradient = MakeGradient(lr.startColor);
            line.validColorGradient = MakeGradient(lr.startColor);
            line.invalidColorGradient = MakeGradient(new Color(0.8f, 0.2f, 0.2f, 0.8f));

            // Minimal controller model
            var model = GameObject.CreatePrimitive(PrimitiveType.Capsule);
            model.name = "Model";
            model.transform.SetParent(go.transform, false);
            model.transform.localScale = new Vector3(0.04f, 0.08f, 0.04f);
            model.transform.localPosition = new Vector3(0, 0, 0.08f);
            Destroy(model.GetComponent<Collider>());
            var mr = model.GetComponent<MeshRenderer>();
            mr.material = new Material(Shader.Find("Standard"));
            mr.material.color = isLeft ? new Color(0.25f, 0.75f, 0.95f, 1f) : new Color(0.95f, 0.55f, 0.2f, 1f);

            // Keep right-hand actions for XR UI input module binding.
            if (!isLeft)
            {
                _rightPos = positionAction;
                _rightRot = rotationAction;
                _rightSelect = selectAction;
                _rightUIPress = uiPressAction;
                _rightUIScroll = new InputAction($"{name}/UIScroll", InputActionType.Value, $"<XRController>{hand}/thumbstick");
                _rightUIScroll.Enable();
            }

            return go;
        }

        private static Gradient MakeGradient(Color c)
        {
            var g = new Gradient();
            g.SetKeys(
                new[] { new GradientColorKey(new Color(c.r, c.g, c.b, 1f), 0f), new GradientColorKey(new Color(c.r, c.g, c.b, 1f), 1f) },
                new[] { new GradientAlphaKey(Mathf.Clamp01(c.a), 0f), new GradientAlphaKey(0f, 1f) }
            );
            return g;
        }

        private void EnsureEventSystemXrUi()
        {
            var es = FindObjectOfType<EventSystem>();
            if (es == null)
            {
                var esGo = new GameObject("EventSystem");
                es = esGo.AddComponent<EventSystem>();
            }

            // Remove non-XR modules.
            var standalone = es.GetComponent<StandaloneInputModule>();
            if (standalone != null)
                Destroy(standalone);

            var inputSystemUi = es.GetComponent<InputSystemUIInputModule>();
            if (inputSystemUi != null)
                Destroy(inputSystemUi);

            if (es.GetComponent<XRUIInputModule>() == null)
                es.gameObject.AddComponent<XRUIInputModule>();

            var module = es.GetComponent<XRUIInputModule>();
            if (module == null)
                return;

            // Bind tracked device + click actions (right hand) so UI can be clicked with ray.
            TrySetActionReference(module, "m_TrackedDevicePosition", _rightPos);
            TrySetActionReference(module, "m_TrackedDeviceOrientation", _rightRot);
            TrySetActionReference(module, "m_LeftClick", _rightUIPress);
            TrySetActionReference(module, "m_ScrollWheel", _rightUIScroll);
        }

        private static void TrySetActionReference(Component module, string fieldName, InputAction action)
        {
            if (action == null)
                return;

            try
            {
                var fi = module.GetType().GetField(fieldName, BindingFlags.Instance | BindingFlags.NonPublic | BindingFlags.Public);
                if (fi == null)
                    return;
                if (fi.FieldType != typeof(InputActionReference))
                    return;
                fi.SetValue(module, InputActionReference.Create(action));
            }
            catch
            {
                // ignore
            }
        }
    }
}
