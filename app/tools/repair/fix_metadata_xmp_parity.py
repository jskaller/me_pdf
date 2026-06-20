#!/usr/bin/env python3
"""
fix_metadata_xmp_parity.py
Enforces Montefiore-required metadata values and synchronises the PDF Info
dictionary with the XMP metadata packet. Also sets catalog-level entries
required by PDF/UA-1 clause 7.1:
  - /Lang in document catalog (7.1.1)
  - /ViewerPreferences/DisplayDocTitle = true (7.1.2)
  - /MarkInfo/Marked = true (7.1.3)

Required fixed values:
  Author/Creator/Producer = "Montefiore Einstein"

Descriptive fields — MUST be derived from document content and passed
explicitly. The script fails with MISSING_REQUIRED_ARGS if these cannot
be determined from args or source PDF.

Usage:
  fix_metadata_xmp_parity.py <input.pdf> <output.pdf>
    --title "Document Title"
    --subject "One sentence subject"
    --keywords "keyword1, keyword2, keyword3"
    [--description "..."]
    [--language en-US]
    [--out results.json]

Exit codes: 0=success, 1=missing required args, 2=error
"""
import sys, json, re, argparse, html
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

ARTIFACT_PATTERNS = [
    r'^\d+$',
    r'^health information management$',
    r'^microsoft word',
    r'^adobe acrobat',
    r'^untitled',
    r'^document\d*$',
]

REQUIRED_XMP_NAMESPACES = {
    'dc': 'http://purl.org/dc/elements/1.1/',
    'xmp': 'http://ns.adobe.com/xap/1.0/',
    'pdf': 'http://ns.adobe.com/pdf/1.3/',
    'pdfuaid': 'http://www.aiim.org/pdfua/ns/id/',
}

BASE_XMP_PACKET = '''<?xpacket begin="\ufeff" id="W5M0MpCehiHzreSzNTczkc9d"?>
<x:xmpmeta xmlns:x="adobe:ns:meta/">
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
<rdf:Description rdf:about=""
  xmlns:dc="http://purl.org/dc/elements/1.1/"
  xmlns:xmp="http://ns.adobe.com/xap/1.0/"
  xmlns:pdf="http://ns.adobe.com/pdf/1.3/"
  xmlns:pdfuaid="http://www.aiim.org/pdfua/ns/id/">
</rdf:Description>
</rdf:RDF>
</x:xmpmeta>
<?xpacket end="w"?>'''


def is_meaningful(value, min_words=3):
    if not value or len(value.strip()) < 4:
        return False
    v = value.strip().lower()
    for pattern in ARTIFACT_PATTERNS:
        if re.match(pattern, v, re.I):
            return False
    return len(v.split()) >= min_words

parser = argparse.ArgumentParser()
parser.add_argument('input_pdf')
parser.add_argument('output_pdf')
parser.add_argument('--title',       default=None)
parser.add_argument('--subject',     default=None)
parser.add_argument('--description', default=None)
parser.add_argument('--keywords',    default=None)
parser.add_argument('--language',    default='en-US')
parser.add_argument('--out',         default=None)
args = parser.parse_args()

FIXED_AUTHOR   = 'Montefiore Einstein'
FIXED_CREATOR  = 'Montefiore Einstein'
FIXED_PRODUCER = 'Montefiore Einstein'

try:
    doc = fitz.open(args.input_pdf)
except Exception as e:
    out = json.dumps({'result': 'ERROR', 'error': f'Could not open PDF: {e}'}, indent=2)
    print(out); sys.exit(2)

meta     = doc.metadata or {}
xmp      = doc.get_xml_metadata() or ''
changes  = []
warnings = []

# ── Resolve descriptive fields ────────────────────────────────────────────────

def resolve_field(arg_value, source_value, field_name, min_words=3, required=True):
    if arg_value and is_meaningful(arg_value, min_words=1):
        return arg_value.strip()
    src = re.sub(r'<[^>]+>', '', source_value or '').strip()
    if src and is_meaningful(src, min_words=min_words):
        warnings.append(f'{field_name}: using source PDF value "{src}"')
        return src
    return None if required else ''

title    = resolve_field(args.title,    meta.get('title', ''),    'title',    min_words=3)
subject  = resolve_field(args.subject,  meta.get('subject', ''),  'subject',  min_words=3)
keywords = resolve_field(args.keywords, meta.get('keywords', ''), 'keywords', min_words=1)

missing = []
if not title:    missing.append(f'--title: missing or artifact ("{meta.get("title","")}")')
if not subject:  missing.append(f'--subject: missing or not meaningful ("{meta.get("subject","")}")')
if not keywords: missing.append('--keywords: missing — derive 4-8 terms from document content')

if missing:
    out = json.dumps({
        'result': 'MISSING_REQUIRED_ARGS', 'missing': missing,
        'agent_instruction': (
            'Read the document and pass: (1) --title: main visible heading; '
            '(2) --subject: one sentence purpose; '
            '(3) --keywords: 4-8 comma-separated terms'
        )
    }, indent=2)
    print(out)
    if args.out: Path(args.out).write_text(out)
    sys.exit(1)

description = args.description or ''
language    = args.language

# ── XMP helpers ───────────────────────────────────────────────────────────────

def xml_text(value):
    return html.escape(str(value), quote=False)


def ensure_xmp_packet(xmp_str):
    """Return a usable XMP packet with namespaces required by this repair.

    PyMuPDF returns an empty string for PDFs without catalog metadata. The old
    replacement-only logic inserted nothing into that empty string, leaving Info
    metadata updated but XMP fields absent. Start from a minimal XMP packet in
    that case, and add any missing namespace declarations to existing packets.
    """
    if not xmp_str or '<rdf:RDF' not in xmp_str or '<rdf:Description' not in xmp_str:
        xmp_str = BASE_XMP_PACKET

    match = re.search(r'<rdf:Description\b[^>]*>', xmp_str, flags=re.S)
    if not match:
        return BASE_XMP_PACKET

    desc = match.group(0)
    additions = []
    for prefix, uri in REQUIRED_XMP_NAMESPACES.items():
        if f'xmlns:{prefix}=' not in desc and f'xmlns:{prefix}=' not in xmp_str:
            additions.append(f' xmlns:{prefix}="{uri}"')

    if additions:
        desc_new = desc[:-1] + ''.join(additions) + '>'
        xmp_str = xmp_str[:match.start()] + desc_new + xmp_str[match.end():]
    return xmp_str


def set_xmp_val(tag, value, xmp_str):
    """Remove ALL existing instances of tag (including self-closing), then insert new value.
    This prevents duplicates regardless of how many times the script is run
    or how many pre-existing instances exist in the source XMP.
    Handles both:
      <pdf:Keywords>value</pdf:Keywords>
      <pdf:Keywords/>   (self-closing empty tag)
    """
    xmp_str = ensure_xmp_packet(xmp_str)
    # Remove self-closing instances first e.g. <pdf:Keywords/>
    cleaned = re.sub(
        rf'\s*<{re.escape(tag)}\s*/>\s*',
        '\n', xmp_str, flags=re.S
    )
    # Remove open/close instances e.g. <pdf:Keywords>...</pdf:Keywords>
    cleaned = re.sub(
        rf'\s*<{re.escape(tag)}[^>]*>.*?</{re.escape(tag)}>\s*',
        '\n', cleaned, flags=re.S
    )
    # Insert single clean instance
    new_tag = f'<{tag}>{value}</{tag}>'
    if '</rdf:Description>' in cleaned:
        return cleaned.replace('</rdf:Description>', f'  {new_tag}\n</rdf:Description>', 1)
    return cleaned.replace('</rdf:RDF>', f'  {new_tag}\n</rdf:RDF>', 1)


def remove_xmp_tag(tag, xmp_str):
    cleaned = re.sub(
        rf'\s*<{re.escape(tag)}[^>]*>.*?</{re.escape(tag)}>\s*',
        '\n', xmp_str, flags=re.S
    )
    return (cleaned, cleaned != xmp_str)

# ── Apply Info + XMP fields ───────────────────────────────────────────────────

xmp = ensure_xmp_packet(xmp)

if meta.get('author') != FIXED_AUTHOR:
    meta['author'] = FIXED_AUTHOR
    changes.append(f'set Info.Author = {FIXED_AUTHOR!r}')
xmp = set_xmp_val('dc:creator',
                  f'<rdf:Seq><rdf:li>{xml_text(FIXED_AUTHOR)}</rdf:li></rdf:Seq>', xmp)

if meta.get('creator') != FIXED_CREATOR:
    meta['creator'] = FIXED_CREATOR
    changes.append(f'set Info.Creator = {FIXED_CREATOR!r}')
xmp = set_xmp_val('xmp:CreatorTool', xml_text(FIXED_CREATOR), xmp)

if meta.get('producer') != FIXED_PRODUCER:
    meta['producer'] = FIXED_PRODUCER
    changes.append(f'set Info.Producer = {FIXED_PRODUCER!r}')
xmp = set_xmp_val('pdf:Producer', xml_text(FIXED_PRODUCER), xmp)

if meta.get('title') != title:
    meta['title'] = title
    changes.append(f'set Info.Title = {title!r}')
xmp = set_xmp_val('dc:title',
                  f'<rdf:Alt><rdf:li xml:lang="x-default">{xml_text(title)}</rdf:li></rdf:Alt>', xmp)

if subject:
    if meta.get('subject') != subject:
        meta['subject'] = subject
        changes.append(f'set Info.Subject = {subject!r}')
    xmp = set_xmp_val('dc:description',
                      f'<rdf:Alt><rdf:li xml:lang="x-default">{xml_text(subject)}</rdf:li></rdf:Alt>', xmp)

if keywords:
    if meta.get('keywords') != keywords:
        meta['keywords'] = keywords
        changes.append(f'set Info.Keywords = {keywords!r}')
    xmp = set_xmp_val('pdf:Keywords', xml_text(keywords), xmp)

xmp = set_xmp_val('dc:language',
                  f'<rdf:Bag><rdf:li>{xml_text(language)}</rdf:li></rdf:Bag>', xmp)

xmp = set_xmp_val('pdfuaid:part', '1', xmp)
xmp = set_xmp_val('pdfuaid:amd', '2005', xmp)
xmp, rev_removed = remove_xmp_tag('pdfuaid:rev', xmp)
if rev_removed:
    changes.append('removed pdfuaid:rev (PDF/UA-2 field)')

# ── Save via PyMuPDF (Info + XMP) ─────────────────────────────────────────────

tmp_path = args.output_pdf + '.tmp.pdf'
try:
    doc.set_metadata(meta)
    doc.set_xml_metadata(xmp)
    doc.save(tmp_path, garbage=4, deflate=True)
    doc.close()
except Exception as e:
    Path(tmp_path).unlink(missing_ok=True)
    out = json.dumps({'result': 'ERROR', 'error': f'PyMuPDF save failed: {e}'}, indent=2)
    print(out)
    if args.out: Path(args.out).write_text(out)
    sys.exit(2)

# ── Set catalog-level PDF/UA-1 requirements via pikepdf ──────────────────────
# PyMuPDF does not expose direct catalog manipulation for these entries.
# Requires pikepdf — approved use per AGENTS.md (PyMuPDF cannot fix these).
#
# Sets:
#   /Lang (PDF string, not name) — PDF/UA-1 clause 7.1.1
#   /ViewerPreferences/DisplayDocTitle = true — PDF/UA-1 clause 7.1.2
#   /MarkInfo/Marked = true — PDF/UA-1 clause 7.1.3

try:
    pdf = pikepdf.open(tmp_path)

    # /Lang must be a PDF string (text string), NOT a name object
    # pikepdf.String produces a PDF string; pikepdf.Name produces /name
    pdf.Root['/Lang'] = pikepdf.String(language)
    changes.append(f'set catalog /Lang = "{language}" (text string)')

    # /ViewerPreferences/DisplayDocTitle
    if '/ViewerPreferences' not in pdf.Root:
        pdf.Root['/ViewerPreferences'] = pdf.make_indirect(pikepdf.Dictionary())
    pdf.Root['/ViewerPreferences']['/DisplayDocTitle'] = pikepdf.Boolean(True)
    changes.append('set /ViewerPreferences/DisplayDocTitle = true')

    # /MarkInfo/Marked
    if '/MarkInfo' not in pdf.Root:
        pdf.Root['/MarkInfo'] = pdf.make_indirect(pikepdf.Dictionary())
    pdf.Root['/MarkInfo']['/Marked'] = pikepdf.Boolean(True)
    changes.append('set /MarkInfo/Marked = true')

    pdf.save(args.output_pdf)
    pdf.close()
    Path(tmp_path).unlink(missing_ok=True)

except Exception as e:
    Path(tmp_path).unlink(missing_ok=True)
    out = json.dumps({'result': 'ERROR', 'error': f'pikepdf catalog update failed: {e}'}, indent=2)
    print(out)
    if args.out: Path(args.out).write_text(out)
    sys.exit(2)

result = 'FIXED' if changes else 'ALREADY_CORRECT'

output = json.dumps({
    'input':    args.input_pdf,
    'output':   args.output_pdf,
    'result':   result,
    'changes':  changes,
    'warnings': warnings,
    'metadata_applied': {
        'author': FIXED_AUTHOR, 'creator': FIXED_CREATOR, 'producer': FIXED_PRODUCER,
        'title': title, 'subject': subject, 'keywords': keywords,
        'description': description, 'language': language,
        'catalog_lang': language, 'display_doc_title': True, 'mark_info_marked': True,
        'pdfuaid_part': '1', 'pdfuaid_amd': '2005', 'pdfuaid_rev': 'removed',
    }
}, indent=2)

print(output)
if args.out: Path(args.out).write_text(output)
sys.exit(0)
