using System;
using System.IO;
using System.Linq;
using System.Diagnostics;
using System.Text;
using System.Text.RegularExpressions;

class Launcher {
    static string Quote(string value) {
        var result = new StringBuilder("\"");
        int slashes = 0;
        foreach (char character in value) {
            if (character == '\\') { slashes++; continue; }
            if (character == '"') { result.Append('\\', slashes * 2 + 1); result.Append('"'); slashes = 0; continue; }
            result.Append('\\', slashes); slashes = 0; result.Append(character);
        }
        result.Append('\\', slashes * 2); result.Append('"'); return result.ToString();
    }
    static int Main(string[] args) {
        try {
            var root = AppDomain.CurrentDomain.BaseDirectory;
            var version = File.ReadAllText(Path.Combine(root, "current.txt")).Trim();
            if (!Regex.IsMatch(version, @"\A[0-9][a-zA-Z0-9.\-]{0,63}\z")) throw new Exception();
            if (args.Length == 0) args = new [] { "init" };
            var python = Path.Combine(root, "versions", version, "python", "python.exe");
            var all = new [] { "-I", "-B", "-m", "ragents" }.Concat(args);
            var start = new ProcessStartInfo(python, String.Join(" ", all.Select(Quote).ToArray()));
            start.UseShellExecute = false; start.CreateNoWindow = false;
            start.WorkingDirectory = Path.GetDirectoryName(python);
            using (var process = Process.Start(start)) { process.WaitForExit(); return process.ExitCode; }
        } catch {
            Console.Error.WriteLine("R Agents açılamadı. Kurulumu veya etkin sürümü kontrol edin.");
            return 1;
        }
    }
}
