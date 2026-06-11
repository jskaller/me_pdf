#!/usr/bin/env python3
"""
fix_ocproperties_config_names.py

Fixes PDF/UA-1 clause 7.10 failures where optional content configuration
dictionaries in the OCProperties catalog entry are missing a required `Name`
key.

For each element D[i] in the Configs array or the D dictionary itself, the
dictionary must contain a non-empty Name entry (text string, PDF string or
name object with length > 0).

Responsibility: ensures Names have non-empty values.
Usage: fix_ocproperties_config_names.py <input.pdf> <output.pdf> [--out results.json]
Exit codes: 0=success, 1=missing/invalid args, 2=error
"""
import sys, json, argparse
from pathlib import Path

try:
    import fitz
except Exception as e:
    print(json.dumps({'result': 'ERROR', 'error': f'PyMuPDF unavailable: {e}'}))
    sys.exit(2)

try:
    import pikepdf
except Exception as e:
    print(json.dumps({'result': 'ERROR', 'error': f'pikepdf unavailable: {e}'}))
    sys.exit(2)

parser = argparse.ArgumentParser()
parser.add_argument('input_pdf')
parser.add_argument('output_pdf')
parser.add_argument('--out', default=None, help='Write JSON result to this file')
parser.add_argument('--base-name', default='', help='Optional base name to use as default Name fallback')
args = parser.parse_args()


def resolve_name(existing, fallback_index):
    """Return a non-empty text string for the Name entry."""
    if existing is not None:
        if isinstance(existing, pikepdf.Name):
            value = str(existing)
        else:
            value = str(existing)
        value = value.strip('\x00').strip()
        if value:
            return value
    return f'Config{fallback_index}'


def process(configs, fallback_prefix='Config'):
    """Inject missing Name entries into each dict in configs."""
    changes = []
    if not isinstance(configs, pikepdf.Array):
        return changes
    for i, item in enumerate(configs):
        if not isinstance(item, pikepdf.Dictionary):
            continue
        name_obj = item.get('/Name')
        name_val = resolve_name(name_obj, i)
        if name_obj is None or str(name_obj).strip() != name_val:
            item['/Name'] = pikepdf.String(name_val)
            changes.append(
                f'set OCProperties.Configs[{i}] Name = "{name_val}"'
            )
    return changes


def process_d(d_item, fallback_prefix='D'):
    """Handle D as a single config dictionary rather than an array."""
    changes = []
    if not isinstance(d_item, pikepdf.Dictionary):
        return changes
    # Treat D itself as context and look for its Name
    name_obj = d_item.get('/Name')
    name_val = resolve_name(name_obj, 0)
    if name_obj is None or str(name_obj).strip() != name_val:
        d_item['/Name'] = pikepdf.String(name_val)
        changes.append(
            f'set OCProperties D Name = "{name_val}"'
        )
    # Also process any array-like nested entries that pikepdf may expose
    for key, val in d_item.items():
        if key == '/Configs' and isinstance(val, pikepdf.Array):
            changes.extend(process(val, fallback_prefix='Configs'))
        elif key == '/D' and isinstance(val, pikepdf.Array):
            changes.extend(process(val, fallback_prefix='D'))
    return changes


def main():
    changes = []

    try:
        src = fitz.open(args.input_pdf)
    except Exception as e:
        err = json.dumps({'result': 'ERROR', 'error': f'Could not open PDF: {e}'}, indent=2)
        print(err)
        if args.out:
            Path(args.out).write_text(err)
        sys.exit(2)

    # Write via PyMuPDF first to do OCR/structure pass-through safely.
    tmp_path = args.output_pdf + '.tmp.pdf'
    src.save(tmp_path, garbage=4, deflate=True)
    src.close()

    try:
        pdf = pikepdf.open(tmp_path)
        root = pdf.Root

        oc = root.get('/OCProperties')
        if not isinstance(oc, pikepdf.Dictionary):
            result = {
                'result': 'SKIP',
                'reason': 'No /OCProperties in catalog',
                'changes': []
            }
            print(json.dumps(result, indent=2))
            if args.out:
                Path(args.out).write_text(json.dumps(result, indent=2))
            Path(tmp_path).unlink(missing_ok=True)
            sys.exit(0)

        # The D key in OCProperties can be:
        #  - a single config dictionary
        #  - an array of config dictionaries (per PDF spec)
        d_obj = oc.get('/D')
        if d_obj is None:
            # Nothing to do
            result = {
                'result': 'ALREADY_CORRECT',
                'reason': 'No D key in OCProperties',
                'changes': []
            }
            print(json.dumps(result, indent=2))
            if args.out:
                Path(args.out).write_text(json.dumps(result, indent=2))
            Path(tmp_path).unlink(missing_ok=True)
            sys.exit(0)

        if isinstance(d_obj, pikepdf.Array):
            changes.extend(process(d_obj, fallback_prefix='D'))
        elif isinstance(d_obj, pikepdf.Dictionary):
            changes.extend(process_d(d_obj, fallback_prefix='D'))
        else:
            # Unknown type — best-effort skip
            pass

        # Also ensure the /Configs key, if present, satisfies the same rule.
        # PDF/UA-1 allows D OR array values in Configs; check both.
        configs = oc.get('/Configs')
        if isinstance(configs, pikepdf.Array):
            changes.extend(process(configs, fallback_prefix='Config'))

        # Apply catalog fixups for display behaviour helpful to AT
        if '/ViewerPreferences' not in root:
            root['/ViewerPreferences'] = pdf.make_indirect(pikepdf.Dictionary())
        vp = root['/ViewerPreferences']
        if vp.get('/DisplayDocTitle') is not True:
            vp['/DisplayDocTitle'] = pikepdf.Boolean(True)
            changes.append('set /ViewerPreferences/DisplayDocTitle = true')

        if '/MarkInfo' not in root:
            root['/MarkInfo'] = pdf.make_indirect(pikepdf.Dictionary())
        mi = root['/MarkInfo']
        if mi.get('/Marked') is not True:
            mi['/Marked'] = pikepdf.Boolean(True)
            changes.append('set /MarkInfo/Marked = true')

        lang = root.get('/Lang')
        if lang and isinstance(lang, pikepdf.Name):
            root['/Lang'] = pikepdf.String(str(lang))
            changes.append(f'set /Lang = "{lang}" (text string, was name)')

        pdf.save(args.output_pdf)
        pdf.close()
        Path(tmp_path).unlink(missing_ok=True)

    except Exception as e:
        Path(tmp_path).unlink(missing_ok=True)
        err = json.dumps({'result': 'ERROR', 'error': f'pikepdf catalog update failed: {e}'}, indent=2)
        print(err)
        if args.out:
            Path(args.out).write_text(err)
        sys.exit(2)

    result_val = 'FIXED' if changes else 'ALREADY_CORRECT'
    out = {
        'input': args.input_pdf,
        'output': args.output_pdf,
        'result': result_val,
        'changes': changes,
        'rule': 'PDF/UA-1/7.10',
    }
    print(json.dumps(out, indent=2))
    if args.out:
        Path(args.out).write_text(json.dumps(out, indent=2))
    sys.exit(0)


if __name__ == '__main__':
    main()
