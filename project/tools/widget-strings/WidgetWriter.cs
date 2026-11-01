using System;
using System.IO;
using System.Text;
using UAssetAPI;
using UAssetAPI.ExportTypes;
using UAssetAPI.PropertyTypes.Objects;
using UAssetAPI.UnrealTypes;

// Low-level writer: the Python wrapper validates input hashes and the whole result.
public static class WidgetWriter
{
    private static void SetTarget(UAsset asset, int index, string name, string expected, string target)
    {
        var entry = asset.Exports[index];
        if (entry.ObjectName.ToString() != name || !(entry is NormalExport export))
            throw new InvalidDataException("unexpected export: " + name);
        StrPropertyData found = null;
        foreach (var prop in export.Data)
        {
            if (prop.Name.ToString() != "CharacterToDisplay") continue;
            if (found != null || !(prop is StrPropertyData typed))
                throw new InvalidDataException("unexpected property: " + name);
            found = typed;
        }
        if (found == null || found.Value.Value != expected)
            throw new InvalidDataException("unexpected source value: " + name);
        found.Value = new FString(target, Encoding.Unicode);
    }

    public static int Main(string[] args)
    {
            if (args.Length != 6) return 2;
        try
        {
            if (File.Exists(args[1]) || File.Exists(Path.ChangeExtension(args[1], ".uexp")))
                throw new IOException("candidate exists");
            var asset = new UAsset(args[0], EngineVersion.VER_UE4_27);
            if (asset.Exports.Count != 74) throw new InvalidDataException("unexpected export count");
            SetTarget(asset, 67, "ConfirmKey", args[2], args[3]);
            SetTarget(asset, 66, "ClearButton", args[4], args[5]);
            asset.Write(args[1]);
            return 0;
        }
        catch (Exception exception)
        {
            Console.Error.WriteLine(exception.ToString());
            return 1;
        }
    }
}
