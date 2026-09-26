#!/usr/bin/env python3
"""Render RULES.md -> static/rules.html -> Spiff_Rules.pdf (headless Chrome). Tiny Markdown subset, no dependencies."""
import html, os, re, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def inline(s):
    s = html.escape(s, quote=False)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"(?<!\*)\*(?!\s)(.+?)(?<!\s)\*(?!\*)", r"<em>\1</em>", s)
    s = s.replace("[A]", '<span class="a">[A]</span>')
    return s


def md_to_html(md):
    out, lines, i = [], md.splitlines(), 0
    while i < len(lines):
        ln = lines[i]
        if not ln.strip():
            i += 1
            continue
        if ln.startswith("# "):
            out.append(f"<h1>{inline(ln[2:])}</h1>")
        elif ln.startswith("## "):
            out.append(f"<h2>{inline(ln[3:])}</h2>")
        elif ln.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            head, body = rows[0], [r for r in rows[1:] if not set("".join(r)) <= set("-: ")]
            t = "<table><thead><tr>" + "".join(f"<th>{inline(c)}</th>" for c in head) + "</tr></thead><tbody>"
            for r in body:
                cls = ' class="total"' if "Total" in r[0] else ""
                t += f"<tr{cls}>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>"
            out.append(t + "</tbody></table>")
            continue
        elif ln.startswith("- "):
            items = []
            while i < len(lines) and lines[i].startswith("- "):
                items.append(f"<li>{inline(lines[i][2:])}</li>")
                i += 1
            out.append("<ul>" + "".join(items) + "</ul>")
            continue
        else:
            para = [ln]
            while i + 1 < len(lines) and lines[i + 1].strip() and not re.match(r"(#|\||- )", lines[i + 1]):
                i += 1
                para.append(lines[i])
            out.append(f"<p>{inline(' '.join(para))}</p>")
        i += 1
    return "\n".join(out)


CSS = """
@font-face { font-family: Showdown; src: url("/fonts/BarlowCondensed-ExtraBoldItalic.ttf"); }
@font-face { font-family: ShowdownUp; src: url("/fonts/BarlowCondensed-Bold.ttf"); }
@page { size: Letter; margin: 0.32in 0.42in; }
* { box-sizing: border-box; }
body { font-family: "Inter", system-ui, -apple-system, "Segoe UI", Roboto, Arial, sans-serif; font-size: 8.3pt; line-height: 1.28; color: #111827; margin: 0; }
.sheet { max-width: 7.6in; margin: 0 auto; }
h1 { font-family: Showdown, "Barlow Condensed", Impact, sans-serif; font-weight: 800; font-style: italic; text-transform: uppercase; font-size: 23pt; line-height: 1;
  margin: 0 0 4px; padding: 8px 12px; color: #fff; border-radius: 10px; background: linear-gradient(100deg, #e11d48, #f59e0b 55%, #2563eb); }
h1 + p { margin: 0 0 4px; font-size: 9pt; }
h2 { font-family: Showdown, "Barlow Condensed", Impact, sans-serif; font-weight: 800; font-style: italic; text-transform: uppercase; font-size: 13pt; margin: 7px 0 2px;
  color: #0b1222; border-bottom: 2px solid #f59e0b; padding-bottom: 1px; }
p { margin: 2px 0 4px; }
ul { margin: 2px 0 4px; padding-left: 15px; } li { margin: 1px 0; }
table { width: 100%; border-collapse: collapse; margin: 3px 0 5px; font-size: 8.3pt; }
th { font-family: ShowdownUp, "Barlow Condensed", sans-serif; text-transform: uppercase; letter-spacing: .06em; font-size: 8pt; text-align: left; background: #0b1222; color: #fff; padding: 4px 6px; }
td { padding: 3.5px 6px; border-bottom: 1px solid #e5e7eb; vertical-align: top; }
td:last-child, th:last-child { text-align: right; white-space: nowrap; }
tbody tr:nth-child(even) td { background: #f8fafc; }
tr.total td { background: #fff7d6 !important; font-weight: 700; border-top: 2px solid #f59e0b; font-size: 9pt; }
.a { color: #b45309; font-weight: 700; font-size: 7.5pt; }
.foot { margin-top: 6px; font-size: 7.5pt; color: #6b7280; display: flex; justify-content: space-between; border-top: 1px solid #e5e7eb; padding-top: 4px; }
@media screen { body { background: #e5e7eb; padding: 20px; } .sheet { background: #fff; padding: 0.4in 0.45in; box-shadow: 0 10px 40px rgba(0,0,0,.2); } }
"""


def main():
    md = open(os.path.join(ROOT, "RULES.md"), encoding="utf-8").read()
    body = md_to_html(md)
    page = f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Lakeshore Showdown: Rules</title><style>{CSS}</style></head><body><div class="sheet">{body}
<div class="foot"><span>[A] = assumption to confirm · Standings, payouts and CSV exports on the Admin page</span><span>Lakeshore Showdown · Oct 2026</span></div></div></body></html>"""
    out_html = os.path.join(ROOT, "static", "rules.html")
    open(out_html, "w", encoding="utf-8").write(page)
    base = sys.argv[1] if len(sys.argv) > 1 else None
    src = f"{base}/rules" if base else "file://" + out_html
    pdf = os.path.join(ROOT, "Spiff_Rules.pdf")
    chrome = os.environ.get("CHROME", "google-chrome")
    subprocess.run([chrome, "--headless=new", "--no-sandbox", "--disable-gpu", "--no-pdf-header-footer",
                    f"--print-to-pdf={pdf}", src], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print("wrote", out_html, "and", pdf)


if __name__ == "__main__":
    main()
