#!/usr/bin/env python3
"""Rebuild the Korean (ja slot) Game.locres for a new game build.

Start from the new build's English locres, carry over every existing Korean value whose English
source is unchanged, apply the reviewed translations of new/changed keys, add the build's challenge
'Confirm' key, then compare the whole result against both inputs.
The challenge menu's Confirm key is a generated GUID that changes between builds: the previous build's
key must exist in the previous Korean locres (it is dropped) and the current build's key is appended.
"""
import argparse,hashlib,json,re,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'project/tools/locres-writer'))
import locres_reader
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def tokens(s):return sorted(re.findall(r'\{[^{}]*\}|<[^<>]*>|%[0-9a-z]+',s))
def pair(e):return e['namespace']+'/'+e['key']
def main():
 ap=argparse.ArgumentParser()
 for n in ('new-en','prev-ko','new-translations','prev-en','writer','appender','out','work'):ap.add_argument('--'+n,required=True,type=Path)
 ap.add_argument('--new-en-sha256',required=True);ap.add_argument('--prev-ko-sha256',required=True)
 ap.add_argument('--confirm-key',required=True);ap.add_argument('--prev-confirm-key',required=True)
 a=ap.parse_args()
 if sha(a.new_en)!=a.new_en_sha256 or sha(a.prev_ko)!=a.prev_ko_sha256:raise SystemExit('input hash mismatch')
 new_en=locres_reader.read(a.new_en);prev_ko=locres_reader.read(a.prev_ko);prev_en=locres_reader.read(a.prev_en)
 E={pair(e):e for e in new_en['entries']};K={pair(e):e for e in prev_ko['entries']};O={pair(e):e for e in prev_en['entries']}
 trans=json.loads(a.new_translations.read_text(encoding='utf-8'))
 added=sorted(set(E)-set(O));changed=sorted(k for k in E if k in O and E[k]['source']!=O[k]['source']);removed=sorted(set(O)-set(E))
 if removed:raise SystemExit('keys removed from English: %s'%removed)
 # Every new or changed key must be translated except the unexplained single-character debug text.
 skipped=[k for k in added if E[k]['source']=='b' and E[k]['namespace']=='']
 need=sorted(set(added)|set(changed))
 if sorted(set(need)-set(skipped))!=sorted(trans):raise SystemExit('translation set differs from new/changed keys: %s'%sorted(set(need)-set(skipped)^set(trans)))
 for k,v in trans.items():
  src=E[k]['source']
  if not v or tokens(v)!=tokens(src) or v.count('\n')!=src.count('\n') or v.strip()!=v:raise SystemExit('translation fails checks: '+k)
 targets={}
 for k,e in E.items():
  if k in trans:targets[k]=trans[k]
  elif k in K and k in O and E[k]['source']==O[k]['source'] and K[k]['source']!=E[k]['source']:targets[k]=K[k]['source']
 a.work.mkdir(parents=True,exist_ok=False)
 tfile=a.work/'targets.json';tfile.write_text(json.dumps(targets,ensure_ascii=False,indent=1)+'\n',encoding='utf-8')
 r=subprocess.run([sys.executable,str(ROOT/'project/tools/locres-writer/inject.py'),'--source',str(a.new_en),'--source-sha256',a.new_en_sha256,'--targets',str(tfile),'--targets-sha256',sha(tfile),'--writer',str(a.writer),'--out',str(a.work/'stage1.locres')],capture_output=True,text=True)
 print(r.stdout,r.stderr)
 if r.returncode:raise SystemExit('inject failed')
 r=subprocess.run(['dotnet',str(a.appender),str(a.work/'stage1.locres'),str(a.out),a.confirm_key],capture_output=True,text=True,env={'DOTNET_ROLL_FORWARD':'Major','PATH':'/usr/bin'})
 if r.returncode:raise SystemExit('append failed: '+r.stderr)
 final=locres_reader.read(a.out);F={pair(e):e for e in final['entries']}
 extra='/'+a.confirm_key
 assert set(F)==set(E)|{extra},'key set differs'
 for k,e in F.items():
  if k==extra:
   assert e['source']=='확인' and e['ue_source_string_hash']==K['/'+a.prev_confirm_key]['ue_source_string_hash'],'confirm key'
  else:
   assert e['ue_source_string_hash']==E[k]['ue_source_string_hash'] and e['ue_key_hash']==E[k]['ue_key_hash'] and e['ue_namespace_hash']==E[k]['ue_namespace_hash'],'hash '+k
   want=trans.get(k) or targets.get(k) or E[k]['source']
   assert e['source']==want,'value '+k
 print(json.dumps({'entries':final['entry_count'],'out_sha256':sha(a.out),'translated_new':sorted(trans),'carried_over':len(targets)-len(trans),'left_as_english':sorted(skipped)},ensure_ascii=False,indent=1))
if __name__=='__main__':main()
