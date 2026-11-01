"""Whole-pair verification for the fixed Queen's Domain 4.27 GameMenu asset."""
import copy,struct
OLD='buttonhint_rotateleft'; NEW='buttonhint_rotateright'
def verify(before,after,ua,ub,ea,eb):
 a=copy.deepcopy(before); b=copy.deepcopy(after); x=a['Exports'];y=b['Exports']
 if len(x)!=237 or len(y)!=237: raise ValueError('unexpected export count')
 if x[63]['ObjectName']!='Default__GameMenu_C' or y[63]['ObjectName']!='Default__GameMenu_C': raise ValueError('wrong export')
 def target(e):
  ps=[v for v in e['Data'] if v['Name']=='InspectMenuHints']
  if len(ps)!=1 or len(ps[0]['Value'])!=6: raise ValueError('wrong hints')
  item=ps[0]['Value'][2]; vals=item['Value'];bind=[v for v in vals if v['Name'].startswith('Binding_2_')];text=[v for v in vals if v['Name'].startswith('Text_5_')]
  if len(bind)!=1 or bind[0]['Value']!=-468 or len(text)!=1 or 'TextPropertyData' not in text[0]['$type'] or text[0]['HistoryType']!='StringTableEntry' or text[0]['TableId']!='/Game/StringTables/ImportedStringTable.ImportedStringTable':raise ValueError('wrong target')
  return text[0]
 t1,t2=target(x[63]),target(y[63])
 if t1['Value']!=OLD or t2['Value']!=NEW: raise ValueError('key mismatch')
 t1['Value']=t2['Value']='__TARGET__'
 funcs=0
 for i,(m,n) in enumerate(zip(x,y)):
  if m['ObjectName']!=n['ObjectName'] or m['$type']!=n['$type']:raise ValueError('identity mismatch')
  if 'FunctionExport' in m['$type']:
   funcs+=1
   if m.get('ScriptBytecode') is None or m.get('ScriptBytecodeRaw') is not None or m['ScriptBytecode']!=n.get('ScriptBytecode'):raise ValueError('function differs')
  expected_size=m['SerialSize']+(1 if i==63 else 0); expected_offset=m['SerialOffset']+(1 if i>63 else 0)
  if n['SerialSize']!=expected_size or n['SerialOffset']!=expected_offset:raise ValueError('metadata differs')
  m['SerialSize']=n['SerialSize']=m['SerialOffset']=n['SerialOffset']='__META__'
 if funcs!=62 or a!=b:raise ValueError('parsed structure differs')
 # Check all .uasset bytes, permitting only the known bulk/export offsets and size.
 before_exports=before['Exports']; after_exports=after['Exports']; header=bytearray(ua)
 old_end=max(e['SerialOffset']+e['SerialSize'] for e in before_exports);new_end=max(e['SerialOffset']+e['SerialSize'] for e in after_exports)
 if struct.unpack_from('<q',ua,169)[0]!=old_end:raise ValueError('bulk mismatch')
 struct.pack_into('<q',header,169,new_end)
 if struct.unpack_from('<q',ua,55354)[0]!=before_exports[63]['SerialSize']:raise ValueError('size location mismatch')
 struct.pack_into('<q',header,55354,after_exports[63]['SerialSize'])
 for i in range(64,237):
  pos=55466+(i-64)*104
  if struct.unpack_from('<q',ua,pos)[0]!=before_exports[i]['SerialOffset']:raise ValueError('offset location mismatch')
  struct.pack_into('<q',header,pos,after_exports[i]['SerialOffset'])
 if bytes(header)!=ub:raise ValueError('unexpected header change')
 # Verify all 236 other exports byte-for-byte and enforce continuity.
 for i,(old,new) in enumerate(zip(before_exports,after_exports)):
  s=old['SerialOffset']-len(ua);t=new['SerialOffset']-len(ub)
  if i!=63 and ea[s:s+old['SerialSize']]!=eb[t:t+new['SerialSize']]:raise ValueError('unrelated export bytes changed')
 # Reconstruct the entire .uexp from original, changing only required nested sizes and the one FString.
 expected=bytearray(ea)
 for pos,old in ((61548,653),(61585,600),(61861,39)):
  if struct.unpack_from('<q',expected,pos)[0]!=old:raise ValueError('nested size mismatch')
  struct.pack_into('<q',expected,pos,old+1)
 if struct.unpack_from('<i',expected,61883)[0]!=22 or expected[61887:61909]!=b'buttonhint_rotateleft\x00':raise ValueError('key offset mismatch')
 expected[61883:61909]=struct.pack('<i',23)+b'buttonhint_rotateright\x00'
 if bytes(expected)!=eb:raise ValueError('unexpected export data change')
 return {'exports_verified':237,'unchanged_exports':236,'functions_verified':62,'key_changes':1}
