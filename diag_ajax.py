import requests, re

s = requests.Session()
s.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": "https://www.register.si/",
})

r = s.get("https://www.register.si/", timeout=20)
m = re.search(r'_ajax_nonce["\']?\s*[:=]\s*["\']([a-f0-9]{8,12})["\']', r.text)
nonce = m.group(1) if m else None
print("NONCE:", nonce)
print()

for domain in ["google.si", "test123.si", "hjhgkjghkj.si"]:
    resp = s.post(
        "https://www.register.si/wp-admin/admin-ajax.php",
        data={"action": "get_domain_status", "domain": domain, "_ajax_nonce": nonce},
        timeout=20,
    )
    print(f"--- {domain} ---")
    print("HTTP", resp.status_code)
    print("CT:", resp.headers.get("Content-Type"))
    print("BODY:", repr(resp.text[:500]))
    print()