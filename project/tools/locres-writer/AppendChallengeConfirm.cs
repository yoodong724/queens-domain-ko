using System;
using System.IO;
using System.Linq;
using LocresLib;

// Adds the challenge-dialogue Confirm key of the current build using the existing Confirm translation.
// The key is a generated GUID that the game changes between builds, so it is an argument.
public static class AppendChallengeConfirm
{
    public static int Main(string[] args)
    {
        try
        {
            if (args.Length != 3) throw new ArgumentException("Expected input locres, output locres and the 32-character key.");
            var key = args[2];
            if (key.Length != 32 || !key.All(c => (c >= '0' && c <= '9') || (c >= 'A' && c <= 'F'))) throw new ArgumentException("Key must be 32 hex digits.");
            var file = new LocresFile();
            using (var input = File.OpenRead(args[0])) file.Load(input);
            var common = file.Single(ns => ns.Name == "ImportedStringTable");
            var confirm = common.Single(item => item.Key == "buttonhint_confirm");
            if (confirm.SourceStringHash != Crc.StrCrc32("Confirm") || confirm.Value != "확인")
                throw new InvalidDataException("Unexpected existing Confirm entry.");
            var target = file.Single(ns => ns.Name == "");
            if (target.Any(item => item.Key == key)) throw new InvalidDataException("Key already exists.");
            target.Add(new LocresString(key, confirm.Value, confirm.SourceStringHash));
            using (var output = new FileStream(args[1], FileMode.CreateNew, FileAccess.Write))
                file.Save(output, file.Version);
            return 0;
        }
        catch (Exception e)
        {
            Console.Error.WriteLine(e.Message);
            return 1;
        }
    }
}
