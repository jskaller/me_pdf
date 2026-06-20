#!/usr/bin/env python3
"""
font_inventory.py
Lists all fonts referenced in a PDF with their embedding and ToUnicode status.

Usage: font_inventory.py <pdf> [--out results.json]
"""
import sys, json, argparse
from pathlib import Path

try:
    import fitz
except Exception as e:
    print(json.dumps({'result': 'ERROR', 'error': f'PyMuPDF unavailable: {e}'})); sys.exit(2)

parser = argparse.ArgumentParser()
parser.add_argument('pdf')
parser.add_argument('--out', default=None, help='Write JSON output to this file in addition to stdout')
args = parser.parse_args()


def is_embedded_font_extension(ext):
    """Return True only when PyMuPDF reports a real embedded font program.

    PyMuPDF page.get_fonts(full=True) reports Base-14 fonts such as Helvetica
    with extension "n/a". That value means there is no extractable embedded
    font program, not that the font is embedded. veraPDF clause 7.21.4.1 checks
    the PDF font dictionary for containsFontFile == true, so the inventory must
    not treat "n/a" as embedded.
    """
    normalized = str(ext or '').strip().lower()
    return bool(normalized) and normalized not in {'n/a', 'na', 'none', 'null'}


doc = fitz.open(args.pdf)
fonts = []
issues = []

for page_num, page in enumerate(doc):
    for font in page.get_fonts(full=True):
        xref, ext, font_type, basefont, name, enc, referencer = font
        embedded = is_embedded_font_extension(ext)
        entry = {
            'page':       page_num + 1,
            'xref':       xref,
            'name':       name or basefont,
            'basefont':   basefont,
            'type':       font_type,
            'encoding':   enc,
            'embedded':   embedded,
            'extension':  ext,
        }
        # Check ToUnicode via xref
        if xref:
            try:
                to_unicode = doc.xref_get_key(xref, 'ToUnicode')
                entry['has_to_unicode'] = to_unicode[0] != 'null'
            except Exception:
                entry['has_to_unicode'] = None
        else:
            entry['has_to_unicode'] = None

        if not entry['embedded']:
            issues.append({
                'name': entry['name'],
                'page': page_num + 1,
                'issue': 'not embedded'
            })
        if entry['has_to_unicode'] is False:
            issues.append({
                'name': entry['name'],
                'page': page_num + 1,
                'issue': 'missing ToUnicode'
            })

        # Deduplicate by xref
        if not any(f['xref'] == xref for f in fonts):
            fonts.append(entry)

result = 'PASS' if not issues else 'FAIL'

output = json.dumps({
    'pdf':         args.pdf,
    'result':      result,
    'font_count':  len(fonts),
    'fonts':       fonts,
    'issues':      issues,
    'issue_count': len(issues)
}, indent=2)

print(output)

if args.out:
    Path(args.out).write_text(output)

sys.exit(0 if result == 'PASS' else 1)
