#!/usr/bin/env python3
"""Filelight-style radial disk v7.
Static disk = single clean language ring (arc ∝ project count), core = total projects.
Interactive page: click a language -> its projects fan out as an outer ring.
README legend: language names with click-to-expand project dropdowns.
Usage:
  python3 sunburst.py --user octocat --token PAT
  python3 sunburst.py --data data.json
Outputs: sunburst.svg, index.html, lang-swatch-*.svg, README_SNIPPET.md, live.json
"""
import argparse, colorsys, json, math, os, re, urllib.request, datetime

SIZE = 720; CX = CY = SIZE // 2
HOLE = 78; BG = "#191919"; TAU = 2 * math.pi

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
    
    # Add any repo names you want to hide to this list (lowercase)
    ignore = {(user or "").lower(), "ravijaanthony_test", "hello-world"}
    repos = [r for r in repos if not r.get("fork") and r["name"].lower() not in ignore]
    repos.sort(key=lambda r: r["size"], reverse=True)
  
    kids = []
    for r in repos[:max_repos]:
        langs = get(r["languages_url"], token)
        children = [{"name": k, "value": v} for k, v in langs.items()]
        if not children: children = [{"name": "other", "value": max(r.get("size", 1) * 1024, 1)}]
        tech_by, tool = {}, []
        if scan and token:
            for grp, techs in scan_repo(r, token).items():
                if grp == "Tooling": tool = sorted(techs); continue
                target = next((L for L in LANG_FOR[grp] if L in langs), None) or (max(langs, key=langs.get) if langs else None)
                if target and techs: tech_by.setdefault(target, []).extend(sorted(techs))
        kids.append({"name": r["name"], "_pushed": r.get("pushed_at", ""),
                     "_tech": tech_by, "_tool": tool, "children": children})
    name = user or (get("https://api.github.com/user", token)["login"] if token else "me")
    return {"name": name, "children": kids}

def invert(root):
    langs = {}
    for repo in root["children"]:
        for lg in repo.get("children", []):
            if lg.get("value", 0) <= 0: continue
            e = langs.setdefault(lg["name"], {"name": lg["name"], "_kind": "lang", "value": 0, "children": []})
            e["children"].append({"name": repo["name"], "_kind": "repo", "value": 1})
            e["value"] += 1
    kids = sorted(langs.values(), key=lambda c: -c["value"])
    for e in kids: e["children"].sort(key=lambda c: -c["value"])
    tree = {"name": root["name"], "value": sum(e["value"] for e in kids), "children": kids}
    tree["_projects"] = len(root["children"])
    return tree

def pt(r, a): return CX + r * math.cos(a), CY + r * math.sin(a)
def sector(r0, r1, a0, a1):
    a1 = min(a1, a0 + TAU - 1e-4)
    large = 1 if a1 - a0 > math.pi else 0
    x0, y0 = pt(r1, a0); x1, y1 = pt(r1, a1); x2, y2 = pt(r0, a1); x3, y3 = pt(r0, a0)
    return (f"M{x0:.2f},{y0:.2f} A{r1},{r1} 0 {large} 1 {x1:.2f},{y1:.2f} "
            f"L{x2:.2f},{y2:.2f} A{r0},{r0} 0 {large} 0 {x3:.2f},{y3:.2f} Z")
def color_fam(i, n, d, j):
    v = max(0.40, 0.97 - 0.10 * d - 0.05 * (j % 4))
    r, g, b = colorsys.hsv_to_rgb((i / n) % 1.0, 0.62, v)
    return f"#{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}"

def build_svg(tree, nproj):
    """static readme disk: ONE clean language ring, no outer layer."""
    B = SIZE / 2 - HOLE - 6
    n = len(tree["children"]) or 1
    style = ("<style>.ring{transform-box:view-box;transform-origin:50% 50%;"
             "animation:pop .7s cubic-bezier(.2,.8,.3,1) both}"
             "@keyframes pop{from{opacity:0;transform:scale(.7) rotate(-60deg)}"
             "to{opacity:1;transform:scale(1) rotate(0)}}path:hover{filter:brightness(.65)}</style>")
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {SIZE} {SIZE}" font-family="monospace">',
           f'<rect width="{SIZE}" height="{SIZE}" fill="{BG}"/>', style]
    a = -math.pi / 2
    for i, lang in enumerate(tree["children"]):
        w = TAU * lang["value"] / tree["value"]
        pct = 100.0 * lang["value"] / tree["value"]
        info = f"{int(lang['value'])} projects ({fmtpct(pct)}%)"
        out.append(f'<path d="{sector(HOLE, HOLE + B, a, a + w)}" fill="{color_fam(i, n, 1, 0)}" '
                   f'stroke="#fff" stroke-width="1" class="ring" data-path="/{esc(lang["name"])}" '
                   f'data-size="{info}" data-pct="{fmtpct(pct)}">'
                   f'<title>/{esc(lang["name"])}\n{info}</title></path>')
        a += w
    out.append(f'<circle cx="{CX}" cy="{CY}" r="{HOLE-6}" fill="#202020"/>')
    out.append(f'<text x="{CX}" y="{CY-8}" fill="#eee" font-size="30" font-weight="bold" text-anchor="middle" dominant-baseline="middle">{nproj}</text>')
    out.append(f'<text x="{CX}" y="{CY+18}" fill="#aaa" font-size="11" text-anchor="middle" dominant-baseline="middle" letter-spacing="2">PROJECTS</text></svg>')
    return "\n".join(out)

def export_readme(root, tree, raw_base, out_dir, token=None):
    """Generate elegant, compact README content with Orgs and Timestamp."""
    langs = tree["children"]
    n = len(langs) or 1
    
    # Generate swatches
    for i, e in enumerate(langs):
        with open(f"{out_dir}/lang-swatch-{i}.svg", "w") as f:
            f.write(f'<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12"><rect width="12" height="12" fill="{color_fam(i, n, 1, 0)}"/></svg>')
    
    # Build compact legend
    legend_items = []
    for i, e in enumerate(langs):
        legend_items.append(f'<img src="assets/lang-swatch-{i}.svg" width="10" height="10" align="center"> **{esc(e["name"])}**')
    legend_text = " · ".join(legend_items)
    
    # Fetch Organizations you contribute to
    orgs = []
    try:
        org_data = get(f"https://api.github.com/users/{root['name']}/orgs", token)
        orgs = [o["login"] for o in org_data]
    except Exception:
        pass
        
    # Get current UTC time
    now = datetime.datetime.utcnow().strftime("%b %d, %Y at %H:%M UTC")
    
    # Build the main disk section
    L = [
        f'<a href="{raw_base}/index.html">', 
        '  <img src="assets/sunburst.svg" width="500" alt="My code, visualized as a disk">',
        '</a>',
        '',
        f'<sub>{legend_text}</sub>',
        '',
        f'<sub><i>Languages → Projects → Codebase · Updated {now}</i></sub>',
    ]
    
    if orgs:
        L.append('')
        L.append(f'<sub><b>Contributing to:</b> {" · ".join(orgs)}</sub>')
    
    with open(f"{out_dir}/README_SNIPPET.md", "w") as f:
        f.write("\n".join(L))
    
    # Generate projects section (separate file for second marker)
    projects_L = []
    def repo_size(c): 
        return sum(child.get("value", 0) for child in c.get("children", []))

    for c in sorted(root["children"], key=lambda c: -repo_size(c))[:8]:  # Top 8 projects
        when = c.get("_pushed", "")[:10]
        langs_list = [g["name"] for g in c.get("children", []) if g["name"] != "Tooling"]
        tech_list = []
        for g in c.get("children", []):
            tech_list.extend(c.get("_tech", {}).get(g["name"], []))
        
        tech_str = " · ".join(langs_list[:3])  # Show max 3 languages
        if tech_list:
            tech_str += " · " + " · ".join(tech_list[:2])  # Show max 2 techs
        
        projects_L.append(f'#### {esc(c["name"])}')
        projects_L.append(f'<sub>{tech_str} · {when}</sub>')
        projects_L.append('')
    
    with open(f"{out_dir}/PROJECTS_SNIPPET.md", "w") as f:
        f.write("\n".join(projects_L))

PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>__TITLE__</title>
<style>
body{background:#191919;margin:0;font-family:monospace;color:#ddd;display:flex;flex-wrap:wrap;justify-content:center;gap:30px;padding:30px;min-height:100vh;box-sizing:border-box}
.disk-wrap{flex:1;min-width:320px;max-width:600px;display:flex;flex-direction:column;align-items:center;position:relative}
svg{width:100%;height:auto}
path{cursor:pointer}path:hover{filter:brightness(.65)}
#tip{position:fixed;display:none;background:#2b2b2b;color:#ddd;border:1px solid #555;padding:8px 12px;font:13px/1.6 monospace;border-radius:4px;pointer-events:none;white-space:nowrap;z-index:10}
#hint{margin-top:12px;font-size:12px;color:#777;text-align:center}
.projects-list{flex:1;min-width:320px;max-width:500px;max-height:85vh;overflow-y:auto;padding:24px;background:#202020;border-radius:8px;border:1px solid #333}
.projects-list h2{margin-top:0;color:#eee;border-bottom:1px solid #444;padding-bottom:12px;font-size:18px}
.project-item{margin-bottom:20px;padding-bottom:20px;border-bottom:1px solid #333}
.project-item:last-child{border-bottom:none}
.project-title{font-size:16px;font-weight:bold;color:#fff}
.project-year{color:#888;font-size:14px;margin-left:8px}
.project-meta{margin:8px 0 0 16px;color:#aaa;font-size:13px;line-height:1.6}
.project-techs{color:#8ab4f8}
</style></head><body>
<div class="disk-wrap">
__SVG__
<div id="hint">hover over the disk for details</div>
</div>
<div class="projects-list" id="projects-list">
<h2>Projects (Latest → Oldest)</h2>
</div>
<div id="tip"></div>
<script>
const PROJECTS=__PROJECTS__;
const esc=s=>String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
const listContainer=document.getElementById('projects-list');
PROJECTS.forEach(p=>{
 const item=document.createElement('div');item.className='project-item';
 let html=`<div class="project-title">${esc(p.name)}<span class="project-year">(${p.year})</span></div>`;
 if(p.langs&&p.langs.length) html+=`<div class="project-meta">- ${p.langs.join(' · ')}</div>`;
 if(p.techs&&p.techs.length) html+=`<div class="project-meta project-techs">- ${p.techs.join(' · ')}</div>`;
 item.innerHTML=html;listContainer.appendChild(item)});

const tip=document.getElementById('tip');
document.querySelector('.disk-wrap').addEventListener('mousemove',e=>{
 const t=e.target.closest('path[data-path]');
 if(!t){tip.style.display='none';return}
 tip.innerHTML=t.dataset.path+'<br>'+t.dataset.size+'<br>'+t.dataset.pct+'% of total';
 tip.style.display='block';tip.style.left=e.clientX+14+'px';tip.style.top=e.clientY+10+'px'});
document.querySelector('.disk-wrap').addEventListener('mouseleave',()=>tip.style.display='none');
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
    tree = invert(root)
    
    # Build the projects list for the interactive page
    projects_data = []
    for repo in sorted(root["children"], key=lambda r: r.get("_pushed", ""), reverse=True):
        year = repo.get("_pushed", "")[:4] or "N/A"
        langs = [c["name"] for c in repo.get("children", []) if c["name"] != "Tooling"]
        techs = []
        for lang_techs in repo.get("_tech", {}).values():
            techs.extend(lang_techs)
        tools = repo.get("_tool", [])
        
        projects_data.append({
            "name": repo["name"],
            "year": year,
            "langs": langs,
            "techs": list(set(techs + tools))
        })

    svg = build_svg(tree, len(root["children"]))
    open(f"{a.out_dir}/sunburst.svg", "w").write(svg)
    
    # Inject both SVG and Projects data into the HTML
    open(f"{a.out_dir}/index.html", "w").write(
        PAGE.replace("__SVG__", svg)
            .replace("__PROJECTS__", json.dumps(projects_data))
            .replace("__TITLE__", root["name"])
    )
    json.dump(tree, open(f"{a.out_dir}/live.json", "w"))
    raw_base = (f"https://raw.githubusercontent.com/{a.repo}/main/assets" if a.repo
                else "https://raw.githubusercontent.com/USER/REPO/main/assets")
    export_readme(root, tree, raw_base, a.out_dir, a.token)
    if a.readme and os.path.exists(a.readme):
        txt = open(a.readme).read()
        
        # Update SUNBURST section
        snip = open(f"{a.out_dir}/README_SNIPPET.md").read()
        txt = re.sub(r"<!-- SUNBURST:START -->.*?<!-- SUNBURST:END -->",
                    lambda m: f"<!-- SUNBURST:START -->\n{snip}\n<!-- SUNBURST:END -->", 
                    txt, flags=re.S)

        open(a.readme, "w").write(txt)
        print("updated README.md")
    print("wrote sunburst.svg, index.html, live.json, swatches, README_SNIPPET.md")

if __name__ == "__main__":
    main()
