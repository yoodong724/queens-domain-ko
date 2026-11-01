"""Verify the fixed UE4.27 widget's full parsed structure and serialized bytes."""
import copy
import struct


TARGETS = {66: 'ClearButton', 67: 'ConfirmKey'}
HEADER_FIELDS = [(66, 'SerialSize', 28089), (67, 'SerialSize', 28193), (67, 'SerialOffset', 28201),
                 (68, 'SerialOffset', 28305), (69, 'SerialOffset', 28409), (70, 'SerialOffset', 28513),
                 (71, 'SerialOffset', 28617), (72, 'SerialOffset', 28721), (73, 'SerialOffset', 28825)]


def fail(message):
    raise ValueError('verification failed: ' + message)


def property_value(entry):
    props = [p for p in entry['Data'] if p.get('Name') == 'CharacterToDisplay']
    if len(props) != 1 or 'StrPropertyData' not in props[0].get('$type', ''):
        fail('unexpected target property')
    return props[0]


def verify(before, after, before_asset, after_asset, before_exp, after_exp, sources, targets):
    old_exports, new_exports = before['Exports'], after['Exports']
    if len(old_exports) != 74 or len(new_exports) != 74 or len(before_asset) != len(after_asset):
        fail('asset layout differs')
    normal_before, normal_after = copy.deepcopy(before), copy.deepcopy(after)
    for index, name in TARGETS.items():
        old, new = old_exports[index], new_exports[index]
        if old['ObjectName'] != name or new['ObjectName'] != name:
            fail('target export differs: ' + name)
        if property_value(old)['Value'] != sources[name] or property_value(new)['Value'] != targets[name]:
            fail('target value differs: ' + name)
        property_value(normal_before['Exports'][index])['Value'] = '__TARGET__'
        property_value(normal_after['Exports'][index])['Value'] = '__TARGET__'

    functions = 0
    for index, (old, new) in enumerate(zip(old_exports, new_exports)):
        if old['ObjectName'] != new['ObjectName'] or old['$type'] != new['$type']:
            fail('export identity differs')
        if 'FunctionExport' in old['$type']:
            functions += 1
            if old.get('ScriptBytecode') is None or old.get('ScriptBytecodeRaw') is not None:
                fail('unsupported function bytecode')
            if old.get('ScriptBytecode') != new.get('ScriptBytecode'):
                fail('function bytecode differs')
        if index not in TARGETS and old['SerialSize'] != new['SerialSize']:
            fail('unrelated export size differs')
        for field in ('SerialOffset', 'SerialSize'):
            normal_before['Exports'][index][field] = normal_after['Exports'][index][field] = '__SERIAL_METADATA__'
    if functions != 23 or normal_before != normal_after:
        fail('parsed structure differs')

    expected_header = bytearray(before_asset)
    for index, field, position in HEADER_FIELDS:
        if struct.unpack_from('<q', before_asset, position)[0] != old_exports[index][field]:
            fail('source header field differs')
        struct.pack_into('<q', expected_header, position, new_exports[index][field])
    old_end = max(e['SerialOffset'] + e['SerialSize'] for e in old_exports)
    new_end = max(e['SerialOffset'] + e['SerialSize'] for e in new_exports)
    if struct.unpack_from('<q', before_asset, 169)[0] != old_end:
        fail('source bulk offset differs')
    struct.pack_into('<q', expected_header, 169, new_end)
    if bytes(expected_header) != after_asset:
        fail('unexpected header bytes')

    old_cursor = new_cursor = len(before_asset)
    unchanged = 0
    for index, (old, new) in enumerate(zip(old_exports, new_exports)):
        if old['SerialOffset'] != old_cursor or new['SerialOffset'] != new_cursor:
            fail('noncontiguous export data')
        old_start, new_start = old_cursor - len(before_asset), new_cursor - len(after_asset)
        old_bytes = before_exp[old_start:old_start + old['SerialSize']]
        new_bytes = after_exp[new_start:new_start + new['SerialSize']]
        if len(old_bytes) != old['SerialSize'] or len(new_bytes) != new['SerialSize']:
            fail('truncated export data')
        old_cursor += old['SerialSize']
        new_cursor += new['SerialSize']
        if index not in TARGETS:
            if old_bytes != new_bytes:
                fail('unrelated export bytes differ: ' + old['ObjectName'])
            unchanged += 1
            continue
        name = TARGETS[index]
        source = sources[name]
        original = struct.pack('<i', len(source) + 1) + source.encode('ascii') + b'\x00'
        target_bytes = targets[name].encode('utf-16le')
        replacement = struct.pack('<i', -(len(target_bytes) // 2 + 1)) + target_bytes + b'\x00\x00'
        if old_bytes.count(original) != 1 or new_bytes.count(replacement) != 1:
            fail('target FString bytes differ: ' + name)
        offset = old_bytes.find(original)
        if offset != 25 or new_bytes.find(replacement) != offset:
            fail('target FString offset differs: ' + name)
        if (old_bytes[:16] != new_bytes[:16] or old_bytes[20:offset] != new_bytes[20:offset]
                or struct.unpack_from('<i', old_bytes, 16)[0] != len(original)
                or struct.unpack_from('<i', new_bytes, 16)[0] != len(replacement)
                or old_bytes[offset + len(original):] != new_bytes[offset + len(replacement):]):
            fail('unexpected target export bytes: ' + name)
    if before_exp[old_cursor-len(before_asset):] != after_exp[new_cursor-len(after_asset):]:
        fail('trailer differs')
    return {'exports_verified': len(old_exports), 'unchanged_exports': unchanged, 'functions_verified': functions,
            'targets_verified': len(TARGETS)}
