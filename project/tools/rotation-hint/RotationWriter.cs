using System;
using System.IO;
using System.Linq;
using System.Text;
using UAssetAPI;
using UAssetAPI.ExportTypes;
using UAssetAPI.PropertyTypes.Objects;
using UAssetAPI.PropertyTypes.Structs;
using UAssetAPI.UnrealTypes;

public static class RotationWriter {
 public static int Main(string[] args) {
  if (args.Length != 2) return 2;
  try {
   if (File.Exists(args[1]) || File.Exists(Path.ChangeExtension(args[1], ".uexp"))) throw new IOException("output exists");
   var a=new UAsset(args[0],EngineVersion.VER_UE4_27);
   if (a.Exports.Count!=237 || a.Exports[63].ObjectName.ToString()!="Default__GameMenu_C" || !(a.Exports[63] is NormalExport e)) throw new InvalidDataException("unexpected export");
   var hints=e.Data.Where(p=>p.Name.ToString()=="InspectMenuHints").ToArray();
   if (hints.Length!=1 || !(hints[0] is ArrayPropertyData arr) || arr.Value.Length!=6 || !(arr.Value[2] is StructPropertyData item)) throw new InvalidDataException("unexpected array");
   var binding=item.Value.Where(p=>p.Name.ToString().StartsWith("Binding_2_")).ToArray();
   var text=item.Value.Where(p=>p.Name.ToString().StartsWith("Text_5_")).ToArray();
   if(binding.Length!=1 || !(binding[0] is ObjectPropertyData b) || b.Value.Index!=-468 || text.Length!=1 || !(text[0] is TextPropertyData t) || t.HistoryType.ToString()!="StringTableEntry" || t.TableId.ToString()!="/Game/StringTables/ImportedStringTable.ImportedStringTable" || t.Value.Value!="buttonhint_rotateleft") throw new InvalidDataException("unexpected binding or text");
   t.Value=new FString("buttonhint_rotateright", Encoding.UTF8);
   a.Write(args[1]);
   return 0;
  } catch(Exception ex) {Console.Error.WriteLine(ex.ToString());return 1;}
 }
}
