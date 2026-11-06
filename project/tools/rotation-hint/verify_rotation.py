"""Whole-pair verification for the GameMenu rotation-hint key correction (UE 4.27 cooked asset).

Positions inside the binary files are derived from the parsed export tables and from the byte
differences themselves, so the check follows game rebuilds without fixed offsets.
"""
import copy,struct
OLD='buttonhint_rotateleft'; NEW='buttonhint_rotateright'
TABLE='/Game/StringTables/ImportedStringTable.ImportedStringTable'
def hint_text(export,imports):
 ps=[v for v in export['Data'] if v['Name']=='InspectMenuHints']
 if len(ps)!=1 or len(ps[0]['Value'])!=6: raise ValueError('wrong hints')
 vals=ps[0]['Value'][2]['Value']
 bind=[v for v in vals if v['Name'].startswith('Binding_2_')]; text=[v for v in vals if v['Name'].startswith('Text_5_')]
 if len(bind)!=1 or bind[0]['Value']>=0 or imports[-bind[0]['Value']-1]['ObjectName']!='KBOrbitHintRight':raise ValueError('wrong target binding')
 if len(text)!=1 or 'TextPropertyData' not in text[0]['$type'] or text[0]['HistoryType']!='StringTableEntry' or text[0]['TableId']!=TABLE:raise ValueError('wrong target')
 return text[0]
def locate_export_table(header,exports):
 """Offset of export 0's (SerialSize, SerialOffset) pair; the table stride is the 104-byte UE4.27 FObjectExport."""
 needle=struct.pack('<qq',exports[0]['SerialSize'],exports[0]['SerialOffset'])
 base=header.find(needle)
 if base<0 or header.find(needle,base+1)>=0:raise ValueError('export table not found uniquely')
 for i,e in enumerate(exports):
  if struct.unpack_from('<qq',header,base+104*i)!=(e['SerialSize'],e['SerialOffset']):raise ValueError('export table stride mismatch')
 return base
def verify(before,after,ua,ub,ea,eb):
 a=copy.deepcopy(before); b=copy.deepcopy(after); x=a['Exports'];y=b['Exports']
 if len(x)!=len(y) or a['Imports']!=b['Imports']:raise ValueError('export/import tables differ')
 names=[i for i,e in enumerate(x) if e['ObjectName']=='Default__GameMenu_C']
 if len(names)!=1 or y[names[0]]['ObjectName']!='Default__GameMenu_C':raise ValueError('wrong export')
 t=names[0]
 t1,t2=hint_text(x[t],a['Imports']),hint_text(y[t],b['Imports'])
 if t1['Value']!=OLD or t2['Value']!=NEW: raise ValueError('key mismatch')
 t1['Value']=t2['Value']='__TARGET__'
 funcs=0
 for i,(m,n) in enumerate(zip(x,y)):
  if m['ObjectName']!=n['ObjectName'] or m['$type']!=n['$type']:raise ValueError('identity mismatch')
  if 'FunctionExport' in m['$type']:
   funcs+=1
   if m.get('ScriptBytecode') is None or m.get('ScriptBytecodeRaw') is not None or m['ScriptBytecode']!=n.get('ScriptBytecode'):raise ValueError('function differs')
  expected_size=m['SerialSize']+(1 if i==t else 0); expected_offset=m['SerialOffset']+(1 if i>t else 0)
  if n['SerialSize']!=expected_size or n['SerialOffset']!=expected_offset:raise ValueError('metadata differs')
  m['SerialSize']=n['SerialSize']=m['SerialOffset']=n['SerialOffset']='__META__'
 if a!=b:raise ValueError('parsed structure differs')
 # .uasset: only the bulk-data end and the export table sizes/offsets may change.
 bx,ax=before['Exports'],after['Exports']; header=bytearray(ua)
 old_end=max(e['SerialOffset']+e['SerialSize'] for e in bx);new_end=max(e['SerialOffset']+e['SerialSize'] for e in ax)
 base=locate_export_table(ua,bx)
 bulk=ua.find(struct.pack('<q',old_end))
 if bulk<0 or ua.count(struct.pack('<q',old_end))!=1:raise ValueError('bulk offset not unique')
 struct.pack_into('<q',header,bulk,new_end)
 for i,e in enumerate(ax):struct.pack_into('<qq',header,base+104*i,e['SerialSize'],e['SerialOffset'])
 if bytes(header)!=ub:raise ValueError('unexpected header change')
 # .uexp: every other export is byte-identical, and the target differs by the one FString plus enclosing sizes.
 for i,(old,new) in enumerate(zip(bx,ax)):
  s=old['SerialOffset']-len(ua);u=new['SerialOffset']-len(ub)
  if i!=t and ea[s:s+old['SerialSize']]!=eb[u:u+new['SerialSize']]:raise ValueError('unrelated export bytes changed')
 s=bx[t]['SerialOffset']-len(ua);u=ax[t]['SerialOffset']-len(ub)
 old_t=ea[s:s+bx[t]['SerialSize']];new_t=eb[u:u+ax[t]['SerialSize']]
 old_s=struct.pack('<i',len(OLD)+1)+OLD.encode()+b'\x00';new_s=struct.pack('<i',len(NEW)+1)+NEW.encode()+b'\x00'
 string_pos=None
 for p in [i for i in range(len(old_t)) if old_t.startswith(old_s,i)]:
  rest=old_t[:p]+new_s+old_t[p+len(old_s):]
  if len(rest)!=len(new_t):continue
  diff=[q for q in range(len(rest)) if rest[q]!=new_t[q]]
  if not diff or max(diff)>=p:continue
  # The enclosing property sizes (int64) before the string each grow by one byte of FString length.
  fixed=bytearray(rest);covered=set();fields=0
  for q in diff:
   if q in covered:continue
   for f in range(q-7,q+1):
    if f<0 or f+8>p:continue
    if struct.unpack_from('<q',new_t,f)[0]==struct.unpack_from('<q',old_t,f)[0]+1:
     struct.pack_into('<q',fixed,f,struct.unpack_from('<q',new_t,f)[0]);covered.update(range(f,f+8));fields+=1;break
  if fields==3 and bytes(fixed)==new_t:
   if string_pos is not None:raise ValueError('ambiguous replaced string')
   string_pos=p
 if string_pos is None:raise ValueError('unexpected export data change')
 return {'exports_verified':len(bx),'unchanged_exports':len(bx)-1,'functions_verified':funcs,'key_changes':1}
