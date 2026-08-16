#!/usr/bin/env python3
"""Filelight-style sunburst, v4: rings = languages (most-used at core),
arcs = projects; legend = language leaderboard; deep dive = newest-first."""
import argparse, colorsys, json, math, os, re, urllib.request

SIZE = 720; CX = CY = SIZE // 2
HOLE = 78; MAX_LANGS = 12; BG = "#191919"
STYLE = ("<style>.ring{transform-box:view-box;transform-origin:50% 50%;"
         "animation:pop .7s cubic-bezier(.2,.8,.3,1) both}"
         "@keyframes pop{from{opacity:0;transform:scale(.7) rotate(-60deg)}"
         "to{opacity:1;transform:scale(1) rotate(0)}}"
         + "".join(f".d{i}{{animation-delay:{i*.10:.2f}s}}" for i in range(MAX_LANGS + 2))
         + "path:hover{filter:brightness(.65)}</style>")

TECH = {"react":"React","vue":"Vue","svelte":"Svelte","next":"Next.js","express":"Express",
        "tailwindcss":"Tailwind","vite":"Vite","electron":"Electron","three":"three.js","d3":"d3",
        "django":"Django","flask":"Flask","fastapi":"FastAPI","numpy":"NumPy","pandas":"pandas",
        "torch":"PyTorch","tensorflow":"TensorFlow","scikit-learn":"scikit-learn","pytest":"pytest",
        "serde":"serde","tokio":"tokio","tauri":"Tauri","bevy":"bevy","egui":"egui",
        "gin":"Gin","cobra":"Cobra","rails":"Rails","sinatra":"Sinatra"}
MANIFESTS = [("package.json","js"),("requirements.txt","python"),("cargo.toml","rust"),
             ("go.mod","go"),("gemfile","ruby")]
LANG_FOR = {"js":("TypeScript","JavaScript"),"python":("Python",),"rust":("Rust",),
            "go":("Go",),"ruby":("Ruby",)}

def _deps(kind, text):
    try:
        if kind == "js":
            d = json.loads(text); return list(d.get("dependencies", {})) + list(d.get("devDependencies", {}))
        if kind == "python": return [re.split(r"[=<>!~\[]", l)[0].strip() for l in text.splitlines() if l.strip() and not l.strip().startswith(("#", "["))]
        if kind == "rust":
            out, sec = [], False
            for l in text.splitlines():
                s = l.strip()
                if s.startswith("["): sec = s.startswith("[dependencies")
                elif sec:
                    m = re.match(r"([a-z0-9_-]+)\s*=", s)
                    if m: out.append(m.group(1))
            return out
        if kind == "go": return [l.split()[0].split("/")[-1] for l in text.splitlines() if l.startswith("\t") and "/" in l]
        if kind == "ruby": return re.findall(r"gem\s+['\"]([^'\"]+)", text)
    except Exception: return []
    return []

def human(b):
    if b < 1024: return f"{int(b)} B"
    for u in ("KiB", "MiB", "GiB", "TiB"):
        b /= 1024
        if b < 1024: return f"{b:.1f} {u}"
    return f"{b:.1f} PiB"
def fmtpct(p): return f"{p:.0f}" if p >= 10 else f"{p:.1f}"
def esc(s): return s.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;").replace('"',"&quot;")
def get(url, token=None):
    h = {"User-Agent": "readme-sunburst"}
    if token: h["Authorization"] = f"token {token}"
    with urllib.request.urlopen(urllib.request.Request(url, headers=h)) as r: return json.load(r)
def get_text(url, token=None):
    h = {"User-Agent": "readme-sunburst"}
    if token: h["Authorization"] = f"token {token}"
    with urllib.request.urlopen(urllib.request.Request(url, headers=h)) as r: return r.read().decode(errors="ignore")

def scan_repo(r, token):
    groups = {}
    try:
        tree = get(f"{r['url']}/git/trees/{r['default_branch']}?recursive=1", token)
        paths = [t["path"] for t in tree.get("tree", []) if t["type"] == "blob"]
    except Exception: return groups
    tools = set()
    for p in paths:
        b = p.split("/")[-1].lower()
        if b == "dockerfile" or b.startswith("docker-compose"): tools.add("Docker")
        elif b == "makefile": tools.add("Make")
        elif p.startswith(".github/workflows/"): tools.add("GitHub Actions")
        elif p.endswith(".tf"): tools.add("Terraform")
        elif "kustomization" in b: tools.add("Kubernetes")
        if p.count("/") <= 1:
            for fname, kind in MANIFESTS:
                if b == fname:
                    text = get_text(f"https://raw.githubusercontent.com/{r['full_name']}/{r['default_branch']}/{p}", token)
                    groups.setdefault(kind, set()).update(TECH[d] for d in _deps(kind, text) if d in TECH)
    if tools: groups["Tooling"] = tools
    return groups

def github_tree(user=None, token=None, max_repos=15, include_private=False, scan=True):
    if include_private:
        if not token: raise SystemExit("--include-private needs --token")
        repos = get("https://api.github.com/user/repos?per_page=100&affiliation=owner", token)
    else:
        repos = get(f"https://api.github.com/users/{user}/repos?per_page=100", token)
    repos = [r for r in repos if not r.get("fork")]
    repos.sort(key=lambda r: r["size"], reverse=True)
    kids = []
    for r in repos[:max_repos]:
        langs = get(r["languages_url"], token)
        children = [{"name": k, "value": v} for k, v in langs.items()]
        if not children: children = [{"name": "other", "value": max(r.get("size", 1) * 1024, 1)}]
        if scan and token:
            by = {c["name"]: c for c in children}
            total = sum(langs.values()) or r["size"] * 1024
            for grp, techs in scan_repo(r, token).items():
                if grp == "Tooling":
                    children.append({"name": "Tooling", "children": [{"name": t, "value": total * 0.05} for t in sorted(techs)]})
                else:
                    target = next((L for L in LANG_FOR[grp] if L in by), None) or (max(langs, key=langs.get) if langs else None)
                    if target and techs:
                        v = by[target]["value"] / len(techs)
                        by[target].setdefault("children", []).extend({"name": t, "value": v} for t in sorted(techs))
        kids.append({"name": r["name"], "_pushed": r.get("pushed_at", ""), "children": children})
    name = user or (get("https://api.github.com/user", token)["login"] if token else "me")
    return {"name": name, "children": kids}

def compute(n):
    if n.get("children"): n["value"] = sum(compute(c) for c in n["children"])
    if "value" not in n: n["value"] = 0
    return n["value"]

def rank_languages(kids):
    """[(lang, {"total", "segs":[(repo, val)]})] most-used first; tail merged into 'other'."""
    acc = {}
    for repo in kids:
        for lg in repo.get("children", []):
            if lg["name"] == "Tooling" or lg["value"] <= 0: continue
            e = acc.setdefault(lg["name"], {"total": 0, "segs": []})
            e["total"] += lg["value"]; e["segs"].append((repo["name"], lg["value"]))
    ranked = sorted(acc.items(), key=lambda kv: -kv[1]["total"])
    if len(ranked) > MAX_LANGS:
        head, tail = ranked[:MAX_LANGS - 1], ranked[MAX_LANGS - 1:]
        other = {"total": 0, "segs": []}
        for _, e in tail:
            other["total"] += e["total"]; other["segs"].extend(e["segs"])
        ranked = head + [("other", other)]
    return ranked

def pt(r, a): return CX + r * math.cos(a), CY + r * math.sin(a)
def sector(r0, r1, a0, a1):
    a1 = min(a1, a0 + 2 * math.pi - 1e-4)
    large = 1 if a1 - a0 > math.pi else 0
    x0, y0 = pt(r1, a0); x1, y1 = pt(r1, a1); x2, y2 = pt(r0, a1); x3, y3 = pt(r0, a0)
    return (f"M{x0:.2f},{y0:.2f} A{r1},{r1} 0 {large} 1 {x1:.2f},{y1:.2f} "
            f"L{x2:.2f},{y2:.2f} A{r0},{r0} 0 {large} 0 {x3:.2f},{y3:.2f} Z")
def color_lang(i, n, j):
    v = max(0.45, 0.95 - 0.07 * (j % 5))
    r, g, b = colorsys.hsv_to_rgb((i / n) % 1.0, 0.62, v)
    return f"#{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}"

def build_svg(root):
    compute(root)
    kids = root["children"]
    ranked = rank_languages(kids)
    n = len(ranked) or 1
    total = sum(e["total"] for _, e in ranked) or 1
    B = SIZE / 2 - HOLE - 6
    ths = [max(12.0, B * e["total"] / total) for _, e in ranked]
    s = B / sum(ths)
    ths = [t * s for t in ths]
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {SIZE} {SIZE}" font-family="monospace">',
           f'<rect width="{SIZE}" height="{SIZE}" fill="{BG}"/>', STYLE]
    r0 = float(HOLE)
    for i, ((lang, e), th) in enumerate(zip(ranked, ths)):
        r1 = r0 + th
        a = -math.pi / 2
        for j, (repo, val) in enumerate(sorted(e["segs"], key=lambda x: -x[1])):
            w = 2 * math.pi * val / e["total"]
            p = f"/{lang}/{repo}"
            pct = 100.0 * val / total
            out.append(f'<path d="{sector(r0, r1, a, a + w)}" fill="{color_lang(i, n, j)}" '
                       f'stroke="#fff" stroke-width="1" class="ring d{i}" data-path="{esc(p)}" '
                       f'data-size="{human(val)}" data-pct="{fmtpct(pct)}">'
                       f'<title>{esc(p)}\n{human(val)} ({fmtpct(pct)}%)</title></path>')
            a += w
        r0 = r1
    out.append(f'<circle cx="{CX}" cy="{CY}" r="{HOLE-6}" fill="#202020"/>')
    out.append(f'<text x="{CX}" y="{CY-8}" fill="#eee" font-size="32" font-weight="bold" text-anchor="middle" dominant-baseline="middle">{len(kids)}</text>')
    out.append(f'<text x="{CX}" y="{CY+18}" fill="#aaa" font-size="12" text-anchor="middle" dominant-baseline="middle" letter-spacing="2">PROJECTS</text></svg>')
    return "\n".join(out)

def export_readme(root, raw_base, out_dir):
    kids = sorted(root["children"], key=lambda c: -c["value"])
    ranked = rank_languages(kids)
    n = len(ranked) or 1
    total = sum(e["total"] for _, e in ranked) or 1

    L = ['<table width="100%"><tr>', '<td width="50%" align="center" valign="top">',
         f'<a href="{raw_base}/sunburst.svg">', '  <img src="assets/sunburst.svg" width="100%" alt="language disk">',
         '</a><br>', '<sub>✨ click the disk for the hover-interactive version</sub>', '</td>',
         '<td width="50%" align="left" valign="top">', '<h3>🧑‍💻 Most → Least Used</h3>', '<table>']
    for i, (lang, e) in enumerate(ranked):
        with open(f"{out_dir}/lang-swatch-{i}.svg", "w") as f:
            f.write(f'<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12"><rect width="12" height="12" fill="{color_lang(i, n, 0)}"/></svg>')
        L.append(f'<tr><td><img src="assets/lang-swatch-{i}.svg" width="12" height="12"></td>'
                 f'<td>&nbsp;<b>{esc(lang)}</b></td><td align="right">&nbsp;{fmtpct(100.0 * e["total"] / total)}%</td></tr>')
    L += ['</table>', '</td>', '</tr></table>', '', '<h3>🕘 Latest Projects <sub>(newest → oldest)</sub></h3>']

    for c in sorted(kids, key=lambda c: c.get("_pushed", ""), reverse=True):
        when = c.get("_pushed", "")[:10]
        L += ['<details>', f'<summary>📁 <b>{esc(c["name"])}</b> · {when}</summary>', '',
              '| language | size |', '|---|---|']
        for g in sorted(c.get("children", []), key=lambda x: -x["value"]):
            if g["name"] == "Tooling":
                L.append(f'| 🛠 tooling | {", ".join(t["name"] for t in g.get("children", []))} |')
            else:
                techs = ", ".join(t["name"] for t in g.get("children", []))
                L.append(f'| {esc(g["name"])} | {human(g["value"])}' + (f" — {techs}" if techs else "") + ' |')
        L += ['', '</details>', '']
    with open(f"{out_dir}/README_SNIPPET.md", "w") as f: f.write("\n".join(L))

PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>__TITLE__</title>
<style>body{background:#191919;margin:0;display:grid;place-items:center;min-height:100vh}
svg{width:min(92vmin,760px);height:auto}path{cursor:pointer}path:hover{filter:brightness(.65)}
#tip{position:fixed;display:none;background:#2b2b2b;color:#ddd;border:1px solid #555;padding:8px 12px;font:13px/1.6 monospace;border-radius:4px;pointer-events:none;white-space:nowrap}</style></head><body>
__SVG__
<div id="tip"></div>
<script>
const tip=document.getElementById('tip');
for(const p of document.querySelectorAll('path[data-path]')){
p.addEventListener('mousemove',e=>{tip.innerHTML=p.dataset.path+'<br>'+p.dataset.size+'<br>'+p.dataset.pct+'% of total';tip.style.display='block';tip.style.left=(e.clientX+14)+'px';tip.style.top=(e.clientY+10)+'px'});
p.addEventListener('mouseleave',()=>tip.style.display='none')}
</script></body></html>"""

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--user"); ap.add_argument("--token"); ap.add_argument("--data")
    ap.add_argument("--max-repos", type=int, default=15)
    ap.add_argument("--include-private", action="store_true")
    ap.add_argument("--no-scan", action="store_true")
    ap.add_argument("--repo"); ap.add_argument("--out-dir", default="."); ap.add_argument("--readme")
    a = ap.parse_args()
    os.makedirs(a.out_dir, exist_ok=True)
    root = (github_tree(a.user, a.token, a.max_repos, a.include_private, scan=not a.no_scan)
            if (a.user or a.include_private) else json.load(open(a.data)))
    svg = build_svg(root)
    open(f"{a.out_dir}/sunburst.svg", "w").write(svg)
    open(f"{a.out_dir}/index.html", "w").write(PAGE.replace("__SVG__", svg).replace("__TITLE__", root["name"]))
    json.dump(root, open(f"{a.out_dir}/live.json", "w"))
    raw_base = (f"https://raw.githubusercontent.com/{a.repo}/main/assets" if a.repo
                else "https://raw.githubusercontent.com/USER/REPO/main/assets")
    export_readme(root, raw_base, a.out_dir)
    if a.readme and os.path.exists(a.readme):
        txt = open(a.readme).read()
        snip = open(f"{a.out_dir}/README_SNIPPET.md").read()
        new = re.sub(r"<!-- SUNBURST:START -->.*?<!-- SUNBURST:END -->",
                     lambda m: f"<!-- SUNBURST:START -->\n{snip}\n<!-- SUNBURST:END -->", txt, flags=re.S)
        if new != txt:
            open(a.readme, "w").write(new)
            print("updated README.md")
    print("wrote sunburst.svg, index.html, live.json, swatches, README_SNIPPET.md")

if __name__ == "__main__":
    main()
