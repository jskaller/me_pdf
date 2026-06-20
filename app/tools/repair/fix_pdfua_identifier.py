#!/usr/bin/env python3
"""
fix_pdfua_identifier.py
Ensures the PDF/UA-1 identifier is correctly set in the XMP metadata.

Sets:
  pdfuaid:part = 1
  pdfuaid:amd  = 2005

Removes:
  pdfuaid:rev  (PDF/UA-2 field — must not be present in PDF/UA-1 documents)

Rerun veraPDF PDF/UA-1 after applying.

Usage: fix_pdfua_identifier.py <input.pdf> <output.pdf> [--out results.json]
"""
import sys, json, re, argparse
from pathlib import Path

try:
    import fitz
except Exception as e:
    print(json.dumps({'result': 'ERROR', 'error': f'PyMuPDF unavailable: {e}'}))
    sys.exit(2)

parser = argparse.ArgumentParser()
parser.add_argument('input_pdf')
parser.add_argument('output_pdf')
parser.add_argument('--out', default=None,
                    help='Write JSON result to this file in addition to stdout')
args = parser.parse_args()

PDFUAID_NS_URI = 'http://www.aiim.org/pdfua/ns/id/'
PDFUAID_NS   = f'xmlns:pdfuaid="{PDFUAID_NS_URI}"'
PDFUAID_PART = '<pdfuaid:part>1</pdfuaid:part>'
PDFUAID_AMD  = '<pdfuaid:amd>2005</pdfuaid:amd>'

BASE_XMP_PACKET = '''<?xpacket begin="\ufeff" id="W5M0MpCehiHzreSzNTczkc9d"?>
<x:xmpmeta xmlns:x="adobe:ns:meta/">
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
<rdf:Description rdf:about="" xmlns:pdfuaid="http://www.aiim.org/pdfua/ns/id/">
</rdf:Description>
</rdf:RDF>
</x:xmpmeta>
<?xpacket end="w"?>'''


def ensure_xmp_packet(xmp_str):
    """Return a usable XMP packet with the PDF/UA namespace declared."""
    if not xmp_str or '<rdf:RDF' not in xmp_str or '<rdf:Description' not in xmp_str:
        return BASE_XMP_PACKET

    if 'xmlns:pdfuaid=' in xmp_str:
        return xmp_str

    match = re.search(r'<rdf:Description\b[^>]*>', xmp_str, flags=re.S)
    if not match:
        return BASE_XMP_PACKET
    desc = match.group(0)
    desc_new = desc[:-1] + f' {PDFUAID_NS}>'
    return xmp_str[:match.start()] + desc_new + xmp_str[match.end():]


doc = fitz.open(args.input_pdf)
xmp = ensure_xmp_packet(doc.get_xml_metadata() or '')

changes = []
if xmp != (doc.get_xml_metadata() or ''):
    changes.append('initialized XMP packet with pdfuaid namespace')

# ── Set pdfuaid:part = 1 ──────────────────────────────────────────────────────
if '<pdfuaid:part>' not in xmp:
    xmp = xmp.replace(
        '</rdf:Description>',
        f'  {PDFUAID_PART}\n  {PDFUAID_AMD}\n</rdf:Description>',
        1
    )
    changes.append('injected pdfuaid:part=1 and pdfuaid:amd=2005')
else:
    current = re.search(r'<pdfuaid:part>(\d+)</pdfuaid:part>', xmp)
    if current and current.group(1) != '1':
        xmp = re.sub(r'<pdfuaid:part>\d+</pdfuaid:part>', PDFUAID_PART, xmp)
        changes.append(f'corrected pdfuaid:part from {current.group(1)} to 1')

# ── Set pdfuaid:amd = 2005 ────────────────────────────────────────────────────
if '<pdfuaid:amd>' not in xmp:
    xmp = xmp.replace('</rdf:Description>', f'  {PDFUAID_AMD}\n</rdf:Description>', 1)
    changes.append('injected pdfuaid:amd=2005')
else:
    current_amd = re.search(r'<pdfuaid:amd>(.*?)</pdfuaid:amd>', xmp)
    if current_amd and current_amd.group(1) != '2005':
        xmp = re.sub(r'<pdfuaid:amd>.*?</pdfuaid:amd>', PDFUAID_AMD, xmp)
        changes.append(f'corrected pdfuaid:amd from {current_amd.group(1)} to 2005')

# ── Remove pdfuaid:rev (PDF/UA-2 only) ───────────────────────────────────────
if '<pdfuaid:rev>' in xmp:
    xmp = re.sub(r'\s*<pdfuaid:rev>.*?</pdfuaid:rev>\s*', '\n', xmp, flags=re.S)
    changes.append('removed pdfuaid:rev (PDF/UA-2 field, not applicable to PDF/UA-1)')

# ── Save ──────────────────────────────────────────────────────────────────────
if changes:
    doc.set_xml_metadata(xmp)
    result = 'FIXED'
else:
    result = 'ALREADY_CORRECT'

doc.save(args.output_pdf, garbage=4, deflate=True)

output = json.dumps({
    'input':   args.input_pdf,
    'output':  args.output_pdf,
    'result':  result,
    'changes': changes
}, indent=2)

print(output)
if args.out:
    Path(args.out).write_text(output)

sys.exit(0)
