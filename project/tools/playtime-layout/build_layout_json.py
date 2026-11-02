#!/usr/bin/env python3
"""Construct a single purpose 13480 save-slot layout candidate."""
import copy
import hashlib
import json
import sys
from pathlib import Path


def prop(export, name):
    found = [p for p in export['Data'] if p['Name'] == name]
    if len(found) != 1:
        raise ValueError(f'{export["ObjectName"]}: expected one {name}')
    return found[0]


def offset(export, name):
    layout = prop(export, 'LayoutData')
    margins = [p for p in layout['Value'] if p['Name'] == 'Offsets']
    if len(margins) != 1:
        raise ValueError('unexpected canvas offsets')
    vals = [p for p in margins[0]['Value'] if p['Name'] == name]
    if len(vals) != 1:
        raise ValueError(f'unexpected {name}')
    return vals[0]


def build(asset):
    exports = asset['Exports']
    if len(exports) != 87 or len(asset['DependsMap']) != 87:
        raise ValueError('unexpected asset export structure')
    expected = {13: 'CanvasPanel_140', 20: 'CanvasPanelSlot_13',
                21: 'CanvasPanelSlot_22', 22: 'CanvasPanelSlot_25',
                40: 'PlayTime', 41: 'PlayTimeLabel', 46: 'HorizontalBox_0',
                48: 'HorizontalBoxSlot_0', 49: 'HorizontalBoxSlot_1',
                50: 'HorizontalBoxSlot_2', 82: 'Spacer_284', 87: 'WidgetTree'}
    for index, name in expected.items():
        if exports[index - 1]['ObjectName'] != name:
            raise ValueError(f'unexpected export {index}')
    if prop(exports[39], 'Slot')['Value'] != 22 or prop(exports[40], 'Slot')['Value'] != 20:
        raise ValueError('unexpected text slot bindings')

    canvas = exports[12]
    children = prop(canvas, 'Slots')['Value']
    if [item['Value'] for item in children].count(20) != 1 or [item['Value'] for item in children].count(22) != 1:
        raise ValueError('unexpected canvas children')
    new_children = []
    for item in children:
        if item['Value'] == 20:
            clone = copy.deepcopy(item)
            clone['Value'] = 89
            new_children.append(clone)
        elif item['Value'] != 22:
            new_children.append(item)
    prop(canvas, 'Slots')['Value'] = new_children
    deps = canvas['CreateBeforeSerializationDependencies']
    if deps.count(20) != 1 or deps.count(22) != 1:
        raise ValueError('unexpected canvas dependency list')
    canvas['CreateBeforeSerializationDependencies'] = [89 if value == 20 else value for value in deps if value != 22]

    # Reuse the existing two slot indices so the text widgets retain their bindings.
    label_slot = copy.deepcopy(exports[48])
    label_slot['ObjectName'] = 'HorizontalBoxSlot_1'
    label_slot['OuterIndex'] = 88
    prop(label_slot, 'Parent')['Value'] = 88
    prop(label_slot, 'Content')['Value'] = 41
    label_slot['CreateBeforeSerializationDependencies'] = [41]
    label_slot['CreateBeforeCreateDependencies'] = [88]
    exports[19] = label_slot

    time_slot = copy.deepcopy(exports[47])
    time_slot['ObjectName'] = 'HorizontalBoxSlot_0'
    time_slot['OuterIndex'] = 88
    prop(time_slot, 'Parent')['Value'] = 88
    prop(time_slot, 'Content')['Value'] = 40
    time_slot['CreateBeforeSerializationDependencies'] = [40]
    time_slot['CreateBeforeCreateDependencies'] = [88]
    exports[21] = time_slot

    row = copy.deepcopy(exports[45])
    row['ObjectName'] = 'HorizontalBox_1'
    row['OuterIndex'] = 87
    for item, index in zip(prop(row, 'Slots')['Value'], (91, 20, 22), strict=True):
        item['Value'] = index
    prop(row, 'Slot')['Value'] = 89
    row['CreateBeforeSerializationDependencies'] = [91, 20, 22, 89]
    row['CreateBeforeCreateDependencies'] = [87]

    canvas_slot = copy.deepcopy(exports[20])
    canvas_slot['ObjectName'] = 'CanvasPanelSlot_100'
    offset(canvas_slot, 'Top')['Value'] = 77.0
    # The date row's shorter slot clips Hangul descenders when reused unchanged.
    offset(canvas_slot, 'Bottom')['Value'] = 40.0
    prop(canvas_slot, 'Content')['Value'] = 88
    canvas_slot['CreateBeforeSerializationDependencies'] = [88]

    spacer = copy.deepcopy(exports[81])
    spacer['ObjectName'] = 'Spacer_285'
    prop(spacer, 'Slot')['Value'] = 91
    spacer['CreateBeforeSerializationDependencies'] = [91]

    spacer_slot = copy.deepcopy(exports[49])
    spacer_slot['ObjectName'] = 'HorizontalBoxSlot_2'
    spacer_slot['OuterIndex'] = 88
    prop(spacer_slot, 'Parent')['Value'] = 88
    prop(spacer_slot, 'Content')['Value'] = 90
    spacer_slot['CreateBeforeSerializationDependencies'] = [90]
    spacer_slot['CreateBeforeCreateDependencies'] = [88]

    exports.extend((row, canvas_slot, spacer, spacer_slot))
    asset['DependsMap'].extend(([], [], [], []))
    if len(asset['Generations']) != 1 or asset['Generations'][0]['ExportCount'] != 87:
        raise ValueError('unexpected generation metadata')
    asset['Generations'][0]['ExportCount'] = 91
    return asset


def main():
    if len(sys.argv) != 3:
        raise SystemExit('usage: build_layout_json.py INPUT_JSON OUTPUT_JSON')
    source, destination = map(Path, sys.argv[1:])
    raw = source.read_bytes()
    if hashlib.sha256(raw).hexdigest() != '970400a6287f5c0879faeb1284ddda9b9c2f6d705356afd79da0fb3fb63c1f01':
        raise ValueError('unexpected source widget JSON hash')
    asset = json.loads(raw.decode('utf-8'))
    with destination.open('x', encoding='utf-8') as f:
        json.dump(build(asset), f, ensure_ascii=False, indent=2)
        f.write('\n')


if __name__ == '__main__':
    main()
