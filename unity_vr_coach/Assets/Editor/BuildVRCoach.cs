using System.IO;
using UnityEditor;
using UnityEditor.Build;
using UnityEngine;

namespace LighthouseLayoutCoach.VRCoach.Editor
{
    public static class BuildVRCoach
    {
        private const string OutputDir = "../releases/VRCoach_Windows";
        private const string ExeName = "LighthouseLayoutCoachVRCoach.exe";

        [MenuItem("LighthouseLayoutCoach/Build VR Coach (Windows x64)")]
        public static void BuildWindows64()
        {
            var projectRoot = Path.GetFullPath(Path.Combine(Application.dataPath, ".."));
            var outDir = Path.GetFullPath(Path.Combine(projectRoot, OutputDir));
            Directory.CreateDirectory(outDir);

            var outExe = Path.Combine(outDir, ExeName);
            var scenes = new[] { "Assets/Scenes/CoachScene.unity" };

            var opts = new BuildPlayerOptions
            {
                scenes = scenes,
                locationPathName = outExe,
                target = BuildTarget.StandaloneWindows64,
                options = BuildOptions.None,
            };

            var report = BuildPipeline.BuildPlayer(opts);
            if (report.summary.result != UnityEditor.Build.Reporting.BuildResult.Succeeded)
            {
                throw new BuildFailedException($"VR Coach build failed: {report.summary.result} ({report.summary.totalErrors} errors)");
            }

            Debug.Log($"Built VR Coach: {outExe}");
        }
    }
}
