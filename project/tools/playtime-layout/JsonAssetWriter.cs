using System;
using System.IO;
using UAssetAPI;

public static class JsonAssetWriter
{
    public static int Main(string[] args)
    {
        if (args.Length != 2) return 2;
        try
        {
            if (File.Exists(args[1]) || File.Exists(Path.ChangeExtension(args[1], ".uexp")))
                throw new IOException("Output already exists");
            var asset = UAsset.DeserializeJson(File.ReadAllText(args[0]));
            asset.Write(args[1]);
            return 0;
        }
        catch (Exception exception)
        {
            Console.Error.WriteLine(exception);
            return 1;
        }
    }
}
