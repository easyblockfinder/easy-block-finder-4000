// GUI launcher — UseShellExecute so embeddable pythonw finds its DLLs.
using System;
using System.Diagnostics;
using System.IO;
using System.Windows.Forms;

internal static class Program
{
    [STAThread]
    private static void Main()
    {
        try
        {
            var appDir = Path.GetFullPath(
                AppDomain.CurrentDomain.BaseDirectory.TrimEnd(
                    Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar));
            Directory.SetCurrentDirectory(appDir);

            var mainPy = Path.Combine(appDir, "src", "main.py");
            if (!File.Exists(mainPy))
            {
                Fail(
                    "Cannot find src\\main.py next to EBF4000.exe.\n" +
                    "Reinstall from the official Setup / ZIP release.");
                return;
            }

            string python = null;
            var bundledW = Path.Combine(appDir, "runtime", "pythonw.exe");
            var bundled = Path.Combine(appDir, "runtime", "python.exe");
            if (File.Exists(bundledW)) python = bundledW;
            else if (File.Exists(bundled)) python = bundled;
            else python = FindSystemPythonw();

            if (string.IsNullOrEmpty(python) || !File.Exists(python))
            {
                Fail(
                    "No Python runtime found.\n\n" +
                    "Install the official Windows Setup (Python is bundled),\n" +
                    "or place runtime\\ next to EBF4000.exe.");
                return;
            }

            // UseShellExecute=true: required for embeddable CPython to resolve python3xx.dll
            // from the runtime folder. main.py adds src/ to sys.path itself.
            var psi = new ProcessStartInfo
            {
                FileName = python,
                Arguments = "\"" + mainPy.Replace("\"", "") + "\"",
                WorkingDirectory = appDir,
                UseShellExecute = true,
            };
            Process.Start(psi);
        }
        catch (Exception ex)
        {
            Fail("Failed to start Easy Block Finder 4000:\n\n" + ex.Message);
        }
    }

    private static void Fail(string msg)
    {
        MessageBox.Show(msg, "Easy Block Finder 4000", MessageBoxButtons.OK, MessageBoxIcon.Error);
        Environment.Exit(1);
    }

    private static string FindSystemPythonw()
    {
        var local = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
        var candidates = new[]
        {
            Path.Combine(local, "Programs", "Python", "Python312", "pythonw.exe"),
            Path.Combine(local, "Programs", "Python", "Python311", "pythonw.exe"),
            Path.Combine(local, "Programs", "Python", "Python310", "pythonw.exe"),
        };
        foreach (var c in candidates)
        {
            if (File.Exists(c)) return c;
        }
        return null;
    }
}
