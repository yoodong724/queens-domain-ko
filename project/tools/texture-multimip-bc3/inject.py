#!/usr/bin/env python3
"""Inject BC3 mip chain into this version's single stickbug texture."""
import argparse,hashlib,json,struct,sys
from pathlib import Path
EXPECTED={'uasset':'6d5e644a3b42caab8532b72ba74531c656d2f6cd1e68481e652be21a0bda53de','uexp':'fc2e84e8bed869e05f50671fea21bc3c0e5784c6e985de86f3a9f45ed335c890','ubulk':'c682eb15a98096227e3cf230a2cbce4ec719017f38f33ec0a19d0a771c6e5322'}
LOCATIONS=[('ubulk',0,32768,512,64),('ubulk',32768,8192,256,32),('ubulk',40960,2048,128,16),('uexp',363,512,64,8),('uexp',911,128,32,4),('uexp',1075,64,16,4),('uexp',1175,32,8,4),('uexp',1243,16,4,4),('uexp',1295,16,4,4),('uexp',1347,16,4,4)]
def sha(b):return hashlib.sha256(b).hexdigest()
def main():
 p=argparse.ArgumentParser();p.add_argument('--asset',type=Path,required=True);p.add_argument('--dds',type=Path,required=True);p.add_argument('--dds-sha256',required=True);p.add_argument('--output-dir',type=Path,required=True);a=p.parse_args()
 if a.output_dir.exists():raise ValueError('output exists')
 if a.asset.suffix!='.uasset' or a.asset.stem!='getstickbuggedlol_tx':raise ValueError('unexpected asset name')
 files={ext:a.asset.with_suffix('.'+ext).read_bytes() for ext in EXPECTED}
 for ext,b in files.items():
  if sha(b)!=EXPECTED[ext]:raise ValueError('source fingerprint mismatch: '+ext)
 d=a.dds.read_bytes()
 if sha(d)!=a.dds_sha256.lower():raise ValueError('DDS fingerprint mismatch')
 if len(d)!=128+43792 or d[:4]!=b'DDS ' or struct.unpack_from('<I',d,4)[0]!=124 or d[84:88]!=b'DXT5' or struct.unpack_from('<I',d,76)[0]!=32 or struct.unpack_from('<I',d,80)[0]!=4 or struct.unpack_from('<II',d,12)!=(64,512) or struct.unpack_from('<I',d,28)[0]!=10 or struct.unpack_from('<I',d,24)[0]!=0 or struct.unpack_from('<I',d,112)[0]!=0:raise ValueError('expected single 2D 512x64 DXT5 DDS with 10 mips')
 x=files['uexp'];needle=b'PF_DXT5\0'
 if x.count(needle)!=1:raise ValueError('unexpected texture format')
 pos=x.index(needle)+len(needle);first,count=struct.unpack_from('<II',x,pos);pos+=8
 if (first,count)!=(0,10):raise ValueError('unexpected mip count')
 found=[]
 for i in range(count):
  cooked,flags,elements,size,offset=struct.unpack_from('<IIIIQ',x,pos);pos+=24
  if cooked!=1 or elements!=size or flags not in (72,66817):raise ValueError('unexpected mip metadata')
  sec='uexp' if flags==72 else 'ubulk';start=pos if flags==72 else offset
  if flags==72:pos+=size
  width,height,depth=struct.unpack_from('<III',x,pos);pos+=12
  if depth!=1 or (sec,start,size,width,height)!=LOCATIONS[i]:raise ValueError('unexpected mip location')
  found.append((sec,start,size))
 rebuilt={k:bytearray(v) for k,v in files.items()};cursor=128
 for sec,start,size in found:
  rebuilt[sec][start:start+size]=d[cursor:cursor+size];cursor+=size
 if cursor!=len(d):raise ValueError('DDS payload length mismatch')
 a.output_dir.mkdir();out=a.output_dir/'packroot/QueensDomain/Content/UI/HUD/HUD_Content';out.mkdir(parents=True);records={}
 for ext,b in rebuilt.items():
  path=out/('getstickbuggedlol_tx.'+ext);path.write_bytes(b)
  if path.read_bytes()!=b:raise OSError('output re-read mismatch')
  records[ext]=sha(b)
 report={'source_sha256':EXPECTED,'dds_sha256':sha(d),'output_sha256':records,'mip_count':len(found),'mips':[{'section':s,'offset':o,'size':n} for s,o,n in found]};(a.output_dir/'report.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))
if __name__=='__main__':
 try:main()
 except (OSError,ValueError,struct.error) as e:print('error:',e,file=sys.stderr);sys.exit(1)
