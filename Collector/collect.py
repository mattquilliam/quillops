"""QuillOps collector: pulls Smart Island open data and writes docs/data.json."""
import json, re, urllib.parse, urllib.request
from datetime import datetime, timezone

BASE = "https://smartisland.im/api"
leads, errors = {}, []

def get(path, **q):
    url = f"{BASE}/{path}?" + urllib.parse.urlencode(q)
    req = urllib.request.Request(url, headers={"User-Agent": "QuillOps/0.2"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)

def add(name, lane, reason, src):
    if not name or not str(name).strip():
        return
    name = str(name).strip()
    lead = leads.setdefault(name, {"name": name, "lanes": {}, "src": set()})
    reasons = lead["lanes"].setdefault(lane, [])
    if reason not in reasons:
        reasons.append(reason)
    lead["src"].add(src)

ROLE_RULES = [
    ("it", r"\b(it|helpdesk|service desk|support engineer|systems? admin\w*|developer|technician)\b",
     "Advertising an IT role, which can mean capacity strain"),
    ("network", r"network|infrastructure|systems engineer", "Hiring network or infrastructure skills"),
    ("voip", r"reception|customer service|contact cent|call", "Hiring front-of-house or call roles"),
    ("signatures", r"compliance|administrator|legal|paralegal|finance|accountant|fiduciary",
     "Hiring document-heavy back-office roles"),
]

def jobs():
    by_employer = {}
    for page in (1, 2, 3):
        rows = get("jobs", employerType="private", limit=200, page=page).get("jobs", [])
        for j in rows:
            by_employer.setdefault(j.get("employer"), []).append(j)
        if len(rows) < 200:
            break
    for emp, js in by_employer.items():
        if len(js) >= 3:
            for lane in ("it", "voip", "connectivity"):
                add(emp, lane, f"Hiring {len(js)} roles at once, so likely growing", "jobs")
        for j in js:
            for lane, pattern, why in ROLE_RULES:
                if re.search(pattern, j.get("title", ""), re.I):
                    add(emp, lane, f"{why}: {j.get('title')}", "jobs")

def companies():
    data = get("companies", status="Live", sortCol="incRegDate", sortDir="desc", limit=60)
    for r in data.get("rows", []):
        name = r.get("name") or r.get("companyName")
        for lane in ("it", "voip", "connectivity"):
            add(name, lane, f"Newly registered company ({r.get('incRegDate')}), no incumbent supplier yet", "companies")

PREMISES = r"office|commercial|change of use|retail|hotel|warehouse|industrial|restaurant"

def planning():
    data = get("planning")
    rows = data if isinstance(data, list) else next((v for v in data.values() if isinstance(v, list)), [])
    for r in rows:
        text = " ".join(str(v) for v in r.values() if isinstance(v, str))
        if re.search(PREMISES, text, re.I):
            name = next((r[k] for k in ("applicant", "address", "site", "reference", "id") if r.get(k)), None)
            what = (r.get("proposal") or r.get("description") or text)[:90]
            for lane in ("connectivity", "network", "voip"):
                add(name, lane, f"New premises signal: {what}", "planning")

for step in (jobs, companies, planning):
    try:
        step()
    except Exception as e:  # keep going if one feed fails
        errors.append(f"{step.__name__}: {e}")

out = sorted(leads.values(), key=lambda l: -sum(len(v) for v in l["lanes"].values()))
for l in out:
    l["src"] = sorted(l["src"])
payload = {"updated": datetime.now(timezone.utc).isoformat(timespec="minutes"), "errors": errors, "leads": out[:300]}
with open("docs/data.json", "w") as f:
    json.dump(payload, f, indent=1)
print(f"{len(out)} leads, {len(errors)} errors")
