#!/usr/bin/env python3
"""
ocr_preserve_forms.py

Strategy: `tesseract_textonly_overlay`.

Add a searchable, invisible OCR text layer to a scanned PDF WITHOUT touching
anything else in the document. The source pages, images, geometry, AcroForm,
and widget annotations are never modified -- the only change is an overlaid
text-only content layer per OCR'd page. This is the OCR strategy for the
document class neither stock ocrmypdf invocation can handle:

  - ocrmypdf --skip-text skips any page containing ANY text element, so a
    scanned page with a few incidental characters (page number, watermark)
    is skipped while the pipeline's detector (min-chars threshold) still
    classifies it image-only.
  - ocrmypdf --force-ocr rasterizes page content, destroying AcroForm
    fields and widget interactivity.

Pipeline (per page classified image-only by the same rule as
tools/audit/detect_image_only_pages.py -- char_count < min-chars AND at
least one image):
  1. Render the page to a raster at --dpi via PyMuPDF (rotation-as-displayed).
  2. Run tesseract with `-c textonly_pdf=1` producing a PDF page containing
     ONLY invisible text (render mode 3), plus a TSV for quality metrics and
     an OSD pass for orientation.
  3. Overlay the text-only page onto the ORIGINAL page with pikepdf
     Page.add_overlay, which compensates for target-page /Rotate.
  4. Self-validate the saved output with the project's real audit scripts:
     tools/audit/detect_image_only_pages.py and
     tools/qa/form_field_preservation_audit.py.

Deliberately NOT done: deskew or rotation correction. The page geometry must
stay fixed underneath existing widget rects, so the image is never altered.
Instead, orientation/skew signals are REPORTED per page in `quality_notes`
(universal rule -- always emitted when detected, never gating): OSD-detected
orientation != 0, or low mean word confidence, sets
`skew_or_rotation_detected` so the operator knows OCR accuracy may be
degraded on that page.

Usage:
  ocr_preserve_forms.py <input.pdf> <output.pdf> [--out results.json]
                        [--language eng] [--dpi 300] [--min-chars 30]
                        [--audit-dir DIR]

Output: one JSON object on stdout with at minimum
  {"result": "PASS|ALREADY_CORRECT|FAIL|ERROR", "strategy": "...", "reason": "..."}

Exit codes:
  0  PASS (validated) or ALREADY_CORRECT (no image-only pages; input copied)
  1  FAIL (output written but validation did not pass; see reason)
  2  ERROR (tool failure: tesseract/pikepdf/pymupdf unavailable or crashed)
"""
from __future__ import annotations

import argparse
import csv
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

STRATEGY = 'tesseract_textonly_overlay'
SCRIPT_DIR = Path(__file__).resolve().parent          # tools/repair
TOOLS_DIR = SCRIPT_DIR.parent                          # tools
DETECT_SCRIPT = TOOLS_DIR / 'audit' / 'detect_image_only_pages.py'
FORM_SCRIPT = TOOLS_DIR / 'qa' / 'form_field_preservation_audit.py'
PER_PAGE_TIMEOUT = 300

try:
    import fitz  # PyMuPDF
except Exception as exc:  # pragma: no cover
    print(json.dumps({'result': 'ERROR', 'strategy': STRATEGY,
                      'reason': f'PyMuPDF unavailable: {exc}'}))
    sys.exit(2)

try:
    import pikepdf
except Exception as exc:  # pragma: no cover
    print(json.dumps({'result': 'ERROR', 'strategy': STRATEGY,
                      'reason': f'pikepdf unavailable: {exc}'}))
    sys.exit(2)


def fail_error(reason, out_path=None, **extra):
    payload = {'result': 'ERROR', 'strategy': STRATEGY, 'reason': reason, **extra}
    text = json.dumps(payload, indent=2)
    print(text)
    if out_path:
        try:
            Path(out_path).write_text(text)
        except Exception:
            pass
    sys.exit(2)


def classify_pages(pdf_path, min_chars):
    """Mirror detect_image_only_pages.py: image-bearing pages below the
    char threshold are OCR targets. Returns (targets, page_count)."""
    doc = fitz.open(str(pdf_path))
    targets = []
    for idx in range(len(doc)):
        page = doc[idx]
        chars = len((page.get_text() or '').strip())
        images = len(page.get_images(full=True))
        if chars < min_chars and images > 0:
            targets.append(idx)
    count = len(doc)
    doc.close()
    return targets, count


def osd_orientation(image_path):
    """Return (rotate_degrees, confidence) from tesseract OSD, or (None, None)."""
    try:
        r = subprocess.run(
            ['tesseract', str(image_path), '-', '--psm', '0'],
            capture_output=True, text=True, timeout=PER_PAGE_TIMEOUT,
        )
        rotate = conf = None
        for line in r.stdout.splitlines():
            if line.startswith('Rotate:'):
                rotate = int(line.split(':', 1)[1].strip())
            elif line.startswith('Orientation confidence:'):
                conf = float(line.split(':', 1)[1].strip())
        return rotate, conf
    except Exception:
        return None, None


def mean_word_conf(tsv_path):
    """Return (word_count, mean_confidence) from a tesseract TSV, or (0, None)."""
    try:
        with open(tsv_path, newline='') as fh:
            rows = csv.DictReader(fh, delimiter='\t')
            confs = [float(r['conf']) for r in rows
                     if r.get('conf') not in (None, '', '-1') and (r.get('text') or '').strip()]
        if not confs:
            return 0, None
        return len(confs), round(sum(confs) / len(confs), 1)
    except Exception:
        return 0, None


def run_audit(cmd, audit_json):
    """Run a project audit script; return its parsed JSON (or an error dict)."""
    try:
        proc = subprocess.run([sys.executable] + [str(c) for c in cmd],
                              capture_output=True, text=True, timeout=PER_PAGE_TIMEOUT)
    except Exception as exc:
        return {'result': 'ERROR', 'error': f'{type(exc).__name__}: {exc}'}
    try:
        return json.loads(Path(audit_json).read_text())
    except Exception:
        return {'result': 'ERROR', 'error': 'audit produced no readable JSON',
                'exit_code': proc.returncode, 'stderr': proc.stderr[:1000]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('input', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--out', type=Path, default=None,
                        help='Write the JSON result here as well as stdout')
    parser.add_argument('--language', default='eng',
                        help='Tesseract language code(s), e.g. eng or eng+spa')
    parser.add_argument('--dpi', type=int, default=300)
    parser.add_argument('--min-chars', type=int, default=30,
                        help='Match detect_image_only_pages.py threshold')
    parser.add_argument('--audit-dir', type=Path, default=None,
                        help='Directory for self-validation audit JSONs '
                             '(default: directory of --out, else of output)')
    args = parser.parse_args()

    if not args.input.exists():
        fail_error(f'input not found: {args.input}', args.out)
    if shutil.which('tesseract') is None:
        fail_error('tesseract not in PATH', args.out)
    for script in (DETECT_SCRIPT, FORM_SCRIPT):
        if not script.exists():
            fail_error(f'required audit script missing: {script}', args.out)

    audit_dir = args.audit_dir or (args.out.parent if args.out else args.output.parent)
    audit_dir.mkdir(parents=True, exist_ok=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)

    targets, page_count = classify_pages(args.input, args.min_chars)

    result = {
        'result': 'UNKNOWN',
        'strategy': STRATEGY,
        'input': str(args.input),
        'output': str(args.output),
        'page_count': page_count,
        'ocr_target_pages': [i + 1 for i in targets],
        'language': args.language,
        'dpi': args.dpi,
        'quality_notes': [],
        'skew_or_rotation_detected': False,
        'source_pdf_modified': False,
    }

    if not targets:
        shutil.copy2(args.input, args.output)
        result.update({'result': 'ALREADY_CORRECT',
                       'reason': 'no image-only pages; input copied unchanged'})
        text = json.dumps(result, indent=2)
        print(text)
        if args.out:
            args.out.write_text(text)
        sys.exit(0)

    with tempfile.TemporaryDirectory(prefix='ocr_overlay_') as tmp:
        tmp = Path(tmp)
        layers = {}
        try:
            doc = fitz.open(str(args.input))
            for idx in targets:
                page = doc[idx]
                pix = page.get_pixmap(matrix=fitz.Matrix(args.dpi / 72, args.dpi / 72))
                img = tmp / f'page{idx}.png'
                pix.save(str(img))

                base = tmp / f'layer{idx}'
                proc = subprocess.run(
                    ['tesseract', str(img), str(base),
                     '-l', args.language, '--dpi', str(args.dpi),
                     '-c', 'textonly_pdf=1', 'pdf', 'tsv'],
                    capture_output=True, text=True, timeout=PER_PAGE_TIMEOUT,
                )
                layer_pdf = base.with_suffix('.pdf')
                if proc.returncode != 0 or not layer_pdf.exists():
                    doc.close()
                    fail_error(f'tesseract failed on page {idx + 1}: '
                               f'{proc.stderr.strip()[:500]}', args.out)

                rotate, rot_conf = osd_orientation(img)
                words, conf = mean_word_conf(base.with_suffix('.tsv'))
                note = {
                    'page': idx + 1,
                    'page_rotation': page.rotation,
                    'osd_orientation_rotate': rotate,
                    'osd_orientation_confidence': rot_conf,
                    'words_recognized': words,
                    'mean_word_confidence': conf,
                }
                if (rotate not in (None, 0)) or (conf is not None and conf < 60):
                    note['flag'] = ('orientation_or_skew_suspected -- deskew is '
                                    'deliberately not applied (geometry must stay '
                                    'fixed under form widgets); OCR accuracy may '
                                    'be reduced on this page')
                    result['skew_or_rotation_detected'] = True
                result['quality_notes'].append(note)
                layers[idx] = layer_pdf
            doc.close()
        except subprocess.TimeoutExpired:
            fail_error('tesseract timed out', args.out)
        except Exception as exc:
            fail_error(f'render/OCR failed: {type(exc).__name__}: {exc}', args.out)

        # Overlay text layers onto the ORIGINAL document. Source content,
        # AcroForm, and annotations are untouched; add_overlay compensates
        # for target-page /Rotate (verified).
        try:
            out_pdf = pikepdf.open(str(args.input))
            for idx, layer_path in layers.items():
                layer = pikepdf.open(str(layer_path))
                out_pdf.pages[idx].add_overlay(layer.pages[0])
                layer.close()
            out_pdf.save(str(args.output))
            out_pdf.close()
        except Exception as exc:
            fail_error(f'overlay/save failed: {type(exc).__name__}: {exc}', args.out)

    # ── Self-validation with the project's real audit scripts ────────────────
    det_json = audit_dir / 'ocr_preserve_forms_image_only_pages.json'
    det = run_audit([DETECT_SCRIPT, args.output, '--out', det_json,
                     '--min-chars', str(args.min_chars)], det_json)
    form_json = audit_dir / 'ocr_preserve_forms_form_preservation.json'
    form = run_audit([FORM_SCRIPT, args.input, args.output, '--out', form_json], form_json)

    ocr_ok = (det.get('ocr_required') is False and not det.get('image_only_pages'))
    form_ok = (form.get('result') == 'PASS')

    result['validation'] = {
        'image_only_pages': {'artifact': str(det_json),
                             'result': det.get('result'),
                             'residual_image_only_pages': det.get('image_only_pages')},
        'form_preservation': {'artifact': str(form_json),
                              'result': form.get('result'),
                              'source_field_count': form.get('source_field_count'),
                              'output_field_count': form.get('output_field_count')},
    }

    if ocr_ok and form_ok:
        result['result'] = 'PASS'
    else:
        result['result'] = 'FAIL'
        reasons = []
        if not ocr_ok:
            reasons.append('image-only pages remain after OCR overlay: '
                           f'{det.get("image_only_pages")} -- these pages have no '
                           'machine-recognizable text (photo/blank/handwriting?)')
        if not form_ok:
            reasons.append(f'form-field preservation: {form.get("result")} '
                           f'({form.get("source_field_count")} -> '
                           f'{form.get("output_field_count")})')
        result['reason'] = '; '.join(reasons)

    text = json.dumps(result, indent=2)
    print(text)
    if args.out:
        args.out.write_text(text)
    sys.exit(0 if result['result'] == 'PASS' else 1)


if __name__ == '__main__':
    main()
