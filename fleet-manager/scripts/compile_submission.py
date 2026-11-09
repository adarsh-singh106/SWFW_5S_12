"""Compile the submission with installed Chrome; no renderer dependencies or downloads.

Run from the project root: uv run --no-sync python scripts/compile_submission.py
The ZIP is deterministic for identical inputs; PDF rendering uses installed Chrome.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import subprocess
import tempfile
import zipfile
from pathlib import Path

from package_source_bundle import collect_bundle_files, is_excluded_path, validate_source_files

ROOT = Path(__file__).resolve().parents[1]
STEM = "Adarsh_Singh_SWFW_5S_12"
REQUIRED = [
    "submission/Adarsh_Singh_SWFW_5S_12_FINAL_REPORT.md",
    "submission/MANUAL-ACCEPTANCE-CHECKLIST.md",
    "submission/FINAL-EXECUTION-REPORT.md",
    "submission/diagrams/system-flow.svg",
    "submission/diagrams/architecture.svg",
    "submission/evidence/index.json",
    "submission/evidence/qa-summary.md",
    "submission/evidence/acceptance-matrix.md",
    "submission/evidence/cloud-summary.md",
]


def inline(text: str) -> str:
    value = html.escape(text)
    value = re.sub(r"`([^`]+)`", r"<code>\1</code>", value)
    return re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", value)


def render_markdown(text: str, base: Path) -> str:
    """Render the small, explicit Markdown subset used by the release report."""
    blocks: list[str] = []
    code: list[str] | None = None
    table = False
    for line in text.splitlines():
        if line.startswith("```"):
            if code is None:
                code = []
            else:
                blocks.append("<pre>" + html.escape("\n".join(code)) + "</pre>")
                code = None
            continue
        if code is not None:
            code.append(line)
            continue
        if table and not line.startswith("|"):
            blocks.append("</tbody></table>")
            table = False
        image = re.fullmatch(r"!\[([^\]]*)\]\(([^)]+)\)", line)
        if image:
            caption, relative = image.groups()
            path = (base / relative).resolve()
            if not path.is_file() or not path.is_relative_to(ROOT / "submission"):
                raise RuntimeError(f"Missing or unsafe embedded image: {path}")
            blocks.append(
                f'<figure><img src="{path.as_uri()}" alt="{html.escape(caption)}">'
                f"<figcaption>{inline(caption)}</figcaption></figure>"
            )
        elif line.startswith("|"):
            if re.fullmatch(r"[| :\-]+", line):
                continue
            if not table:
                blocks.append("<table><tbody>")
                table = True
            blocks.append(
                "<tr>"
                + "".join(f"<td>{inline(c.strip())}</td>" for c in line.strip("|").split("|"))
                + "</tr>"
            )
        elif line.startswith("#"):
            level = min(len(line) - len(line.lstrip("#")), 6)
            blocks.append(f"<h{level}>{inline(line[level:].strip())}</h{level}>")
        elif line.startswith("- "):
            blocks.append(f'<p class="bullet">&#8226; {inline(line[2:])}</p>')
        elif line.strip():
            blocks.append(f"<p>{inline(line)}</p>")
    if code is not None:
        raise RuntimeError("Unterminated Markdown code fence")
    if table:
        blocks.append("</tbody></table>")
    return "\n".join(blocks)


CSS = """
@page { size: A4; margin: 16mm 14mm 18mm;
 @bottom-right { content: 'SWFW_5S_12 | ' counter(page); font-size: 9px; color: #566358; }
}
* { box-sizing: border-box; }
body { font: 10pt/1.48 Arial, sans-serif; color: #29302c; background: #fff; }
h1 { font-size: 28pt; margin-top: 40mm; color: #263b30; }
h2 { font-size: 17pt; break-before: page; border-bottom: 2px solid #879b88; padding-bottom: 8px; }
h3 { font-size: 12pt; margin-top: 20px; break-after: avoid; }
p { margin: 7px 0; overflow-wrap: anywhere; }
pre { background: #f3f1eb; border: 1px solid #d6dacf; padding: 10px;
 font: 8pt/1.45 Consolas, monospace; white-space: pre-wrap; overflow-wrap: anywhere; }
code { font-size: 8.5pt; background: #f4f2ec; }
table { width:100%; border-collapse:collapse; font-size:8.3pt; margin:12px 0; }
td { border:1px solid #cbd2ca; padding:6px; vertical-align:top; overflow-wrap:anywhere; }
tr:first-child { font-weight:bold; background:#edf1e9; }
tr { break-inside:avoid; }
figure { margin:16px 0; break-inside:avoid; }
img { display:block; max-width:100%; max-height:205mm; margin:auto; object-fit:contain; }
figcaption { font-size:9pt; color:#59665d; margin:7px 0; }
.bullet { padding-left:12px; }
"""


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def compile_release(root: Path, chrome: Path) -> dict[str, object]:
    missing = [p for p in REQUIRED if not (root / p).is_file()]
    source = collect_bundle_files(root)
    missing += validate_source_files(source)
    if missing:
        raise RuntimeError(f"Required submission inputs missing: {missing}")
    report = root / REQUIRED[0]
    text = report.read_text(encoding="utf-8")
    for image in ("diagrams/system-flow.svg", "diagrams/architecture.svg"):
        if f"]({image})" not in text:
            raise RuntimeError(f"Mandatory embedded diagram absent from report: {image}")
    if not chrome.is_file():
        raise RuntimeError(f"Installed Chrome renderer not found: {chrome}")
    final = root / "submission/final"
    final.mkdir(parents=True, exist_ok=True)
    pdf = final / f"{STEM}.pdf"
    with tempfile.TemporaryDirectory(prefix="fleet_submission_") as temp:
        work = Path(temp)
        document = work / "report.html"
        document.write_text(
            '<!doctype html><html lang="en"><meta charset="utf-8">'
            "<title>SWFW_5S_12 Technical Report</title><style>"
            + CSS
            + "</style><body>"
            + render_markdown(text, report.parent)
            + "</body></html>",
            encoding="utf-8",
        )
        result = subprocess.run(
            [
                str(chrome),
                "--headless=new",
                "--disable-gpu",
                "--no-pdf-header-footer",
                "--allow-file-access-from-files",
                f"--user-data-dir={work / 'profile'}",
                f"--print-to-pdf={pdf}",
                document.as_uri(),
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode or not pdf.is_file() or pdf.stat().st_size < 10000:
            raise RuntimeError(f"PDF renderer failed: {result.returncode}: {result.stderr[-2000:]}")
    if not pdf.read_bytes().startswith(b"%PDF-"):
        raise RuntimeError("Renderer did not produce a PDF")
    files = set(source)
    for path in (root / "submission").rglob("*"):
        rel = path.relative_to(root)
        if path.is_file() and not path.is_symlink() and "final" not in rel.parts:
            if not is_excluded_path(rel):
                files.add(rel)
    # Include this PDF, never earlier archives, recursive output or stale tarballs.
    files.add(pdf.relative_to(root))
    archive = final / f"{STEM}_PROJECT-FILES.zip"
    manifest = []
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
        for rel in sorted(files, key=lambda p: p.as_posix()):
            path = root / rel
            if path.is_symlink():
                raise RuntimeError(f"Symlink not permitted: {rel}")
            data = path.read_bytes()
            if re.search(
                rb"(?m)^-----BEGIN (?:OPENSSH |RSA |EC |ENCRYPTED )?PRIVATE KEY-----\r?$",
                data,
            ):
                raise RuntimeError(f"Private key content detected: {rel}")
            info = zipfile.ZipInfo(rel.as_posix(), date_time=(2026, 11, 9, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o755 if path.suffix in {".sh", ".py"} else 0o644) << 16
            bundle.writestr(info, data)
            manifest.append(
                {
                    "path": rel.as_posix(),
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "bytes": len(data),
                }
            )
    with (
        zipfile.ZipFile(archive) as bundle,
        tempfile.TemporaryDirectory(prefix="fleet_extract_") as temp,
    ):
        if bundle.testzip() is not None:
            raise RuntimeError("ZIP CRC verification failed")
        for name in bundle.namelist():
            if Path(name).is_absolute() or ".." in Path(name).parts:
                raise RuntimeError(f"Unsafe ZIP member: {name}")
        bundle.extractall(temp)
        for item in manifest:
            if digest(Path(temp) / str(item["path"])) != item["sha256"]:
                raise RuntimeError(f"Extracted content mismatch: {item['path']}")
        # Compile extracted application, without writing bytecode into release sources.
        for path in (Path(temp) / "src").rglob("*.py"):
            compile(path.read_bytes(), str(path), "exec")
    checksums = {pdf.name: digest(pdf), archive.name: digest(archive)}
    (final / "SHA256SUMS.txt").write_text(
        "".join(f"{value}  {name}\n" for name, value in checksums.items()), encoding="utf-8"
    )
    result_data = {
        "checksums": checksums,
        "file_count": len(files),
        "integrity": "CRC + clean extraction + SHA-256 + extracted source syntax PASS",
        "files": manifest,
    }
    (final / "package-manifest.json").write_text(
        json.dumps(result_data, indent=2), encoding="utf-8"
    )
    print(json.dumps({k: v for k, v in result_data.items() if k != "files"}, indent=2))
    return result_data


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--chrome",
        type=Path,
        default=Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    )
    args = parser.parse_args()
    compile_release(ROOT, args.chrome)


if __name__ == "__main__":
    main()
