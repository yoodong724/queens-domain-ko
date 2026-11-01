#!/usr/bin/env python3
"""Investigative reader for the observed locres v3; not a general purpose UE parser."""
import argparse
import csv
import hashlib
import json
import struct
from pathlib import Path

MAGIC=bytes.fromhex('0e147475674a03fc4a15909dc3377f1b')

def read(path):
    data=path.read_bytes()
    if data[:16]!=MAGIC or data[16]!=3:
        raise ValueError('expected locres version 3')
    offset=17
    def unpack(fmt):
        nonlocal offset
        val,=struct.unpack_from('<'+fmt,data,offset)
        offset+=struct.calcsize('<'+fmt)
        return val
    def unreal():
        nonlocal offset
        n=unpack('i')
        if n==0: return ''
        size=n if n>0 else -n*2
        raw=data[offset:offset+size]; offset+=size
        if len(raw)!=size: raise ValueError('truncated string')
        text=raw.decode('ascii' if n>0 else 'utf-16-le')
        if not text.endswith('\x00'): raise ValueError('missing terminator')
        return text[:-1]
    table_offset=unpack('q')
    count=unpack('i'); namespaces=unpack('i')
    raw_entries=[]
    for _ in range(namespaces):
        namespace_hash=unpack('I'); namespace=unreal(); key_count=unpack('i')
        for _ in range(key_count):
            key_hash=unpack('I'); key=unreal(); source_hash=unpack('I'); index=unpack('i')
            raw_entries.append((namespace,namespace_hash,key,key_hash,source_hash,index))
    if offset!=table_offset or len(raw_entries)!=count:
        raise ValueError('index boundary/count mismatch')
    n_strings=unpack('i'); values=[]
    for _ in range(n_strings):
        value=unreal(); references=unpack('i'); values.append((value,references))
    if offset!=len(data): raise ValueError('unread trailing bytes')
    entries=[]
    refcounts=[0]*len(values)
    for ns,ns_hash,key,key_hash,source_hash,index in raw_entries:
        if not 0<=index<len(values): raise ValueError('invalid index')
        value=values[index][0]; refcounts[index]+=1
        entries.append({'namespace':ns,'key':key,'source':value,'ue_source_string_hash':f'{source_hash:08x}','source_utf8_sha256':hashlib.sha256(value.encode('utf-8')).hexdigest(),'ue_namespace_hash':f'{ns_hash:08x}','ue_key_hash':f'{key_hash:08x}'})
    if refcounts != [x[1] for x in values]: raise ValueError('string reference count mismatch')
    if len({(x['namespace'],x['key']) for x in entries}) != len(entries): raise ValueError('duplicate namespace/key')
    return {'format':'queens-domain-locres-v3-observation','locres_sha256':hashlib.sha256(data).hexdigest(),'locres_bytes':len(data),'entry_count':len(entries),'namespace_count':namespaces,'unique_value_count':len(values),'entries':entries}

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('input',type=Path); ap.add_argument('output',type=Path); ap.add_argument('--csv',type=Path); args=ap.parse_args()
    result=read(args.input)
    if args.csv:
        with args.csv.open(encoding='utf-8-sig',newline='') as f: rows=list(csv.DictReader(f))
        pairs={(x['namespace']+'/'+x['key']):x['source'] for x in result['entries'] if x['source']}
        if len(pairs)!=sum(bool(x['source']) for x in result['entries']): raise ValueError('ambiguous slash-joined keys')
        exported={r['key']:r['source'] for r in rows}
        if len(exported)!=len(rows) or exported!=pairs: raise ValueError('CSV disagrees with locres')
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('entries:',result['entry_count'],'unique strings:',result['unique_value_count'],'empty:',sum(not x['source'] for x in result['entries']))
if __name__=='__main__': main()
