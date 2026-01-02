using UnityEngine;

namespace LighthouseLayoutCoach.VRCoach
{
    public sealed class CoachBootstrap : MonoBehaviour
    {
        private void Awake()
        {
            if (FindObjectOfType<XRCoachRigBootstrap>() == null)
            {
                gameObject.AddComponent<XRCoachRigBootstrap>();
            }
            if (FindObjectOfType<VRCoachSceneBuilder>() == null)
            {
                gameObject.AddComponent<VRCoachSceneBuilder>();
            }
            if (FindObjectOfType<VRSetupDiagnostics>() == null)
            {
                gameObject.AddComponent<VRSetupDiagnostics>();
            }
        }
    }
}
