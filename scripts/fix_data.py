import json

TEAM_MAP = {
    "Backend-Auth": "IAM-Security",
    "Data-Reporting": "Backend-Reporting",
}
PRIORITY_MAP = {
    "P1": "P1_CRITICAL",
    "P2": "P2_HIGH",
    "P3": "P3_MEDIUM",
    "P4": "P4_LOW",
}

def load(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)

def save(p, data):
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

kb = load("data/knowledge_base.json")
for d in kb:
    d["owner_team"] = TEAM_MAP.get(d["owner_team"], d["owner_team"])
save("data/knowledge_base.json", kb)

tk = load("data/historical_tickets.json")
for t in tk:
    t["assigned_team"] = TEAM_MAP.get(t["assigned_team"], t["assigned_team"])
    t["priority"] = PRIORITY_MAP.get(t["priority"], t["priority"])
save("data/historical_tickets.json", tk)

print("Da chuyen doi xong.")