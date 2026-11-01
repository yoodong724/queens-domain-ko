#!/usr/bin/env python3
"""Checked, fixed-input GameMenu FText-key correction; game/runtime QA remains separate."""
import argparse,hashlib,json,os,subprocess,sys
from pathlib import Path
from verify_rotation import verify
ASSET='a05ca6aceeca55aa890c6464f233acfd47e1ce55396cf175bded9ba03062e326'
EXP='9933c2ba8dc04bdc77288e6b3a9bb7645d5add81b42928335cb5cf9159282220'
def digest(b):return hashlib.sha256(b).hexdigest()
def inspect(tool,asset,out):
 p=subprocess.run(['dotnet',str(tool),str(asset),str(out)],text=True,capture_output=True)
 if p.returncode or 'exports=237 functions=62 parsed=62 raw=0 binaryEqual=True' not in p.stdout:raise ValueError('asset inspection failed: '+p.stdout+p.stderr)
 return json.loads(out.read_text())
def inject(asset,writer,inspector,out):
 if os.path.lexists(out):raise FileExistsError('output already exists')
 if asset.suffix!='.uasset':raise ValueError('expected uasset')
 u=asset.read_bytes(); e=asset.with_suffix('.uexp').read_bytes()
 if digest(u)!=ASSET or digest(e)!=EXP:raise ValueError('source fingerprint mismatch')
 if not writer.is_file() or not inspector.is_file():raise ValueError('required tool missing')
 out.mkdir();work=out/'work';inp=work/'input';cand=work/'candidate';inp.mkdir(parents=True);cand.mkdir()
 src=inp/'GameMenu.uasset';src.write_bytes(u);src.with_suffix('.uexp').write_bytes(e)
 a=inspect(inspector,src,work/'before.json');dst=cand/'GameMenu.uasset';r=subprocess.run(['dotnet',str(writer),str(src),str(dst)],text=True,capture_output=True)
 (work/'writer.log').write_text(r.stdout+r.stderr)
 if r.returncode:raise ValueError('writer failed: '+r.stderr)
 b=inspect(inspector,dst,work/'after.json');ua=dst.read_bytes();ea=dst.with_suffix('.uexp').read_bytes();v=verify(a,b,u,ua,e,ea)
 files=out/'packroot/QueensDomain/Content/UI/Menus';files.mkdir(parents=True);(files/'GameMenu.uasset').write_bytes(ua);(files/'GameMenu.uexp').write_bytes(ea)
 if (files/'GameMenu.uasset').read_bytes()!=ua or (files/'GameMenu.uexp').read_bytes()!=ea:raise ValueError('copy mismatch')
 report={'source_uasset_sha256':digest(u),'source_uexp_sha256':digest(e),'output_uasset_sha256':digest(ua),'output_uexp_sha256':digest(ea),**v,'status':'static_only; all-language UI impact and game runtime unverified'}
 (out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');return report
def main():
 p=argparse.ArgumentParser(description=__doc__)
 for n in ('asset','writer','inspector','out'):p.add_argument('--'+n,type=Path,required=True)
 a=p.parse_args()
 try: print(json.dumps(inject(a.asset,a.writer,a.inspector,a.out),ensure_ascii=False));return 0
 except (OSError,ValueError,TypeError,KeyError,IndexError) as ex:print('error:',str(ex),file=sys.stderr);return 1
if __name__=='__main__':sys.exit(main())
