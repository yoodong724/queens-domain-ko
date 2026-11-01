using System;
using System.Collections.Generic;
using System.IO;
using System.Text.Json;
using LocresLib;

// Internal writer. Input checks and independent post-write verification are
// performed by inject.py; calling this executable directly bypasses them.
public static class LocresWriter
{
    public static int Main(string[] args)
    {
        try
        {
            if (args.Length != 3) throw new ArgumentException("Expected source, target map, output.");
            var targets = JsonSerializer.Deserialize<Dictionary<string, string>>(File.ReadAllText(args[1]))
                ?? throw new InvalidDataException("Missing target map.");
            var file = new LocresFile();
            using (var input = File.OpenRead(args[0])) file.Load(input);
            foreach (var ns in file)
                foreach (var item in ns)
                    if (targets.TryGetValue(ns.Name + "/" + item.Key, out string value))
                        item.Value = value;
            using (var output = new FileStream(args[2], FileMode.CreateNew, FileAccess.Write))
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
