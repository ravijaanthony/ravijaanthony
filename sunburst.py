#!/usr/bin/env python3
"""Filelight-style radial disk v6 — hierarchical sunburst.
Core = total project count. Ring 1 = languages (arc ∝ project count, fills 360°).
Ring 2 = projects subdividing their language's exact arc. Ring 3 = technologies
staying inside their project's angular bounds. Family hue per language,
children inherit shades. index.html gets click-to-zoom (overview → language → project).
Usage:
  python3 sunburst.py --user octocat --token PAT
  python3 sunburst.py --data data.json
Outputs: sunburst.svg, index.html, lang-swatch-*.svg, README_SNIPPET.md, live.json
"""
import argparse, colorsys, json, math, os, re, urllib.request

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
    repos = [r for r in repos if not r.get("fork")]
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
    """repo-first data -> language-first tree: lang(value=#projects) -> repo(value=1) -> techs(sum=1)."""
    langs = {}
    for repo in root["children"]:
        for lg in repo.get("children", []):
            if lg.get("value", 0) <= 0: continue
            e = langs.setdefault(lg["name"], {"name": lg["name"], "_kind": "lang", "value": 0, "children": []})
            node = {"name": repo["name"], "_kind": "repo", "value": 1}
            techs = repo.get("_tech", {}).get(lg["name"], [])
            if techs:
                node["children"] = [{"name": t, "_kind": "tech", "value": 1.0 / len(techs)} for t in techs]
            e["children"].append(node)
            e["value"] += 1
    kids = sorted(langs.values(), key=lambda c: -c["value"])
    for e in kids: e["children"].sort(key=lambda c: -c["value"])
    tree = {"name": root["name"], "value": sum(e["value"] for e in kids), "children": kids}
    tree["_projects"] = len(root["children"])
    return tree

def tree_depth(nd):
    return 1 + max((tree_depth(c) for c in nd.get("children", [])), default=0)
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
    rings = tree_depth(tree) - 1
    th = (SIZE / 2 - HOLE - 6) / rings
    n = len(tree["children"]) or 1
    style = ("<style>.ring{transform-box:view-box;transform-origin:50% 50%;"
             "animation:pop .7s cubic-bezier(.2,.8,.3,1) both}"
             "@keyframes pop{from{opacity:0;transform:scale(.7) rotate(-60deg)}"
             "to{opacity:1;transform:scale(1) rotate(0)}}"
             + "".join(f".d{k}{{animation-delay:{k*.12:.2f}s}}" for k in range(rings + 1))
             + "path:hover{filter:brightness(.65)}</style>")
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {SIZE} {SIZE}" font-family="monospace">',
           f'<rect width="{SIZE}" height="{SIZE}" fill="{BG}"/>', style]

    def draw(nd, d, a0, a1, i, sib, p):
        cp = f"{p}/{nd['name']}"
        info = (f"{int(nd['value'])} projects ({fmtpct(100.0*nd['value']/tree['value'])}%)"
                if nd["_kind"] == "lang" else "1 project" if nd["_kind"] == "repo" else "technology")
        out.append(f'<path d="{sector(HOLE + d*th, HOLE + (d+1)*th, a0, a1)}" '
                   f'fill="{color_fam(i, n, d+1, sib)}" stroke="#fff" stroke-width="1" class="ring d{d}" '
                   f'data-path="{esc(cp)}" data-size="{info}" data-pct="{fmtpct(100.0*nd["value"]/tree["value"])}">'
                   f'<title>{esc(cp)}\n{info}</title></path>')
        if nd.get("children"):
            a = a0
            for j, c in enumerate(nd["children"]):
                w = (a1 - a0) * c["value"] / nd["value"]   # childAngle = parentAngle × child/parent
                draw(c, d + 1, a, a + w, i, j, cp)
                a += w

    a = -math.pi / 2
    for i, lang in enumerate(tree["children"]):
        w = TAU * lang["value"] / tree["value"]
        draw(lang, 0, a, a + w, i, 0, "")
        a += w
    out.append(f'<circle cx="{CX}" cy="{CY}" r="{HOLE-6}" fill="#202020"/>')
    out.append(f'<text x="{CX}" y="{CY-8}" fill="#eee" font-size="30" font-weight="bold" text-anchor="middle" dominant-baseline="middle">{nproj}</text>')
    out.append(f'<text x="{CX}" y="{CY+18}" fill="#aaa" font-size="11" text-anchor="middle" dominant-baseline="middle" letter-spacing="2">PROJECTS</text></svg>')
    return "\n".join(out)

def export_readme(root, tree, raw_base, out_dir):
    langs = tree["children"]
    n = len(langs) or 1
    L = ['<table width="100%"><tr>', '<td width="50%" align="center" valign="top">',
         f'<a href="{raw_base}/sunburst.svg">', '  <img src="assets/sunburst.svg" width="100%" alt="language disk">',
         '</a><br>', '<sub>✨ click the disk for the hover + zoom interactive version</sub>', '</td>',
         '<td width="50%" align="left" valign="top">', '<h3>🧑‍ Languages (by projects)</h3>', '<table>']
    for i, e in enumerate(langs):
        with open(f"{out_dir}/lang-swatch-{i}.svg", "w") as f:
            f.write(f'<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12"><rect width="12" height="12" fill="{color_fam(i, n, 1, 0)}"/></svg>')
        L.append(f'<tr><td><img src="assets/lang-swatch-{i}.svg" width="12" height="12"></td>'
                 f'<td>&nbsp;<b>{esc(e["name"])}</b></td>'
                 f'<td align="right">&nbsp;{int(e["value"])} · {fmtpct(100.0*e["value"]/tree["value"])}%</td></tr>')
    L += ['</table>', '</td>', '</tr></table>', '', '<h3>🕘 Latest Projects <sub>(newest → oldest)</sub></h3>']
    for c in sorted(root["children"], key=lambda c: c.get("_pushed", ""), reverse=True):
        when = c.get("_pushed", "")[:10]
        L += ['<details>', f'<summary>📁 <b>{esc(c["name"])}</b> · {when}</summary>', '', '| language | size |', '|---|---|']
        for g in sorted(c.get("children", []), key=lambda x: -x["value"]):
            techs = ", ".join(c.get("_tech", {}).get(g["name"], []))
            L.append(f'| {esc(g["name"])} | {human(g["value"])}' + (f" — {techs}" if techs else "") + ' |')
        if c.get("_tool"):
            L.append(f'| 🛠 tooling | {", ".join(c["_tool"])} |')
        L += ['', '</details>', '']
    with open(f"{out_dir}/README_SNIPPET.md", "w") as f: f.write("\n".join(L))

PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>__TITLE__</title>
<style>body{background:#191919;margin:0;display:grid;place-items:center;min-height:100vh}
#wrap{position:relative}svg{width:min(92vmin,760px);height:auto}
path{cursor:pointer}path:hover{filter:brightness(.65)}
#crumb{position:absolute;top:8px;left:12px;font:13px monospace;color:#999;cursor:pointer;display:none}
#crumb:hover{color:#fff}
#tip{position:fixed;display:none;background:#2b2b2b;color:#ddd;border:1px solid #555;padding:8px 12px;font:13px/1.6 monospace;border-radius:4px;pointer-events:none;white-space:nowrap}</style></head><body>
<div id="wrap"><div id="crumb">← back</div><div id="chart"></div></div>
<div id="tip"></div>
<script>
const DATA=__DATA__;
const S=720,C=360,HOLE=78,TAU=2*Math.PI;
let view=DATA,stack=[],idmap=[];
const esc=s=>String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
const dep=n=>n.children&&n.children.length?1+Math.max(...n.children.map(dep)):1;
function hsv(h,s,v){const f=h*6,i=Math.floor(f),t=f-i,p=v*(1-s),q=v*(1-s*t),w=v*(1-s*(1-t));
const m=[[v,w,p],[q,v,p],[p,v,w],[p,q,v],[w,p,v],[v,p,q]][i%6];
return"#"+m.map(x=>Math.round(x*255).toString(16).padStart(2,"0")).join("")}
const col=(i,n,d,j)=>hsv((i/n)%1,.62,Math.max(.4,.97-.10*d-.05*(j%4)));
function P(r,a){return[C+r*Math.cos(a),C+r*Math.sin(a)]}
function sec(r0,r1,a0,a1){a1=Math.min(a1,a0+TAU-1e-4);const L=a1-a0>Math.PI?1:0,f=x=>x.toFixed(2);
const[x0,y0]=P(r1,a0),[x1,y1]=P(r1,a1),[x2,y2]=P(r0,a1),[x3,y3]=P(r0,a0);
return`M${f(x0)},${f(y0)} A${r1},${r1} 0 ${L} 1 ${f(x1)},${f(y1)} L${f(x2)},${f(y2)} A${r0},${r0} 0 ${L} 0 ${f(x3)},${f(y3)} Z`}
function node(nd,d,a0,a1,i,n,th,p,out){
 const id=idmap.push(nd)-1,cp=p+"/"+nd.name;
 const t2=nd._kind=="lang"?nd.value+" projects":nd._kind=="repo"?"1 project":"technology";
 out.push(`<path d="${sec(HOLE+d*th,HOLE+(d+1)*th,a0,a1)}" fill="${col(i,n,d+1,0)}" stroke="#fff" data-id="${id}" data-path="${esc(cp)}" data-info="${esc(t2)}"><title>${esc(cp)}\n${esc(t2)}</title></path>`);
 if(nd.children){let a=a0;nd.children.slice().sort((x,y)=>y.value-x.value).forEach((c,j)=>{
   const w=(a1-a0)*c.value/nd.value;node(c,d+1,a,a+w,i,n,th,cp,out);a+=w})}}
function render(){
 idmap=[];
 const rings=dep(view)-1,th=(S/2-HOLE-6)/rings,n=view.children.length||1;
 const out=[`<svg viewBox="0 0 ${S} ${S}" font-family="monospace"><rect width="${S}" height="${S}" fill="#191919"/>`];
 let a=-Math.PI/2;
 view.children.forEach((c,i)=>{const w=TAU*c.value/view.value;node(c,0,a,a+w,i,n,th,"",out);a+=w});
 const num=stack.length?Math.round(view.value):DATA._projects;
 const lab=stack.length?view.name.toUpperCase().slice(0,12):"PROJECTS";
 out.push(`<circle id="core" cx="${C}" cy="${C}" r="${HOLE-6}" fill="#202020" style="cursor:pointer"/>`);
 out.push(`<text x="${C}" y="${C-8}" fill="#eee" font-size="30" font-weight="bold" text-anchor="middle" dominant-baseline="middle" style="pointer-events:none">${num}</text>`);
 out.push(`<text x="${C}" y="${C+18}" fill="#aaa" font-size="11" letter-spacing="2" text-anchor="middle" dominant-baseline="middle" style="pointer-events:none">${lab}</text></svg>`);
 document.getElementById("chart").innerHTML=out.join("");
 document.getElementById("crumb").style.display=stack.length?"block":"none"}
function back(){if(stack.length){view=stack.pop();render()}}
document.getElementById("chart").addEventListener("click",e=>{
 if(e.target.id=="core"){back();return}
 const nd=idmap[e.target.dataset.id];
 if(nd&&nd.children){stack.push(view);view=nd;render()}});
document.getElementById("crumb").onclick=back;
const tip=document.getElementById("tip");
document.getElementById("chart").addEventListener("mousemove",e=>{
 const t=e.target.closest("path[data-path]");
 if(!t){tip.style.display="none";return}
 tip.innerHTML=t.dataset.path+"<br>"+t.dataset.info;
 tip.style.display="block";tip.style.left=e.clientX+14+"px";tip.style.top=e.clientY+10+"px"});
render();
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
    nproj = len(root["children"])
    svg = build_svg(tree, nproj)
    open(f"{a.out_dir}/sunburst.svg", "w").write(svg)
    open(f"{a.out_dir}/index.html", "w").write(PAGE.replace("__DATA__", json.dumps(tree)).replace("__TITLE__", root["name"]))
    json.dump(tree, open(f"{a.out_dir}/live.json", "w"))
    raw_base = (f"https://raw.githubusercontent.com/{a.repo}/main/assets" if a.repo
                else "https://raw.githubusercontent.com/USER/REPO/main/assets")
    export_readme(root, tree, raw_base, a.out_dir)
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
