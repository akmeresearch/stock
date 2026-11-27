import requests, json
r = requests.get("https://akme-sitewatch.akme.workers.dev/", timeout=30)
print(r.status_code); print(json.dumps(r.json(), ensure_ascii=False, indent=1)[:2500])
