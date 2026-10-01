# .si Domain Finder (Hybrid)

Finds free `.si` domains using two sources:

1. **Phase 1 — ARNES DAS** (`das.arnes.si:4343`) — fast, until banned
2. **Phase 2 — register.si AJAX** (`www.register.si`) — slow, HTTPS

When DAS bans your IP, the script auto-switches to register.si. Every 50 web queries it probes DAS again and returns to fast mode if unbanned. Stops cleanly on HTTP 429 from register.si.

Every FREE domain is written to `available_si.csv` immediately (flush + fsync), so Ctrl+C or a crash never loses results.

---

## Setup

Requires **Python 3.8+**.

```powershell
pip install requests certifi
```

## Run

```powershell
cd D:\Smeti\si-domains
python si_hybrid.py https://raw.githubusercontent.com/first20hours/google-10000-english/master/google-10000-english.txt
```

The script:

1. Probes DAS with `google.si`
2. If alive → fast phase (1 s/domain)
3. If banned → slow phase via register.si (3 s/domain)
4. Every 50 queries → re-probes DAS; jumps back if unbanned
5. On HTTP 429 from register.si → stops and saves the CSV

## Wordlists

| List | URL | Size |
|---|---|---|
| Top 10k English | `https://raw.githubusercontent.com/first20hours/google-10000-english/master/google-10000-english.txt` | ~6,600 after filter |
| Top 1k English | `https://raw.githubusercontent.com/first20hours/google-10000-english/master/google-10000-english-usa.txt` | ~800 |
| Full English | `https://raw.githubusercontent.com/dwyl/english-words/master/words_alpha.txt` | ~40,000 after filter |

Only 4–8 letter words (`[a-z]{4,8}`) are kept.

---

## Options

```
python si_hybrid.py <wordlist> [options]

--out FILE        Output CSV (default: available_si.csv)
--limit N         Only check first N words (for testing)
--das-delay SEC   Delay between DAS queries (default: 1.0)
--web-delay SEC   Delay between register.si queries (default: 3.0)
--phase auto|das|web   Start in a specific phase (default: auto)
--reset           Wipe the CSV and start fresh
```

Examples:

```powershell
python si_hybrid.py wordlist.txt --limit 20
python si_hybrid.py wordlist.txt --phase web
python si_hybrid.py wordlist.txt --web-delay 5.0
```

---

## Output

Live console:

```
FREE      brim.si   -> saved to available_si.csv
FREE      quilt.si  -> saved to available_si.csv
[WEB] [1498/6648]  22.5%  FREE: 6  taken: 1400  err: 0
```

Final summary:

```
================ SUMMARY ================
  Checked:    6648/6648
  FREE:       37
  registered: 6611
  errors:     0
  Free ->  available_si.csv
=========================================
```

`available_si.csv`:

```
domain
brim.si
quilt.si
knob.si
```

---

## How responses are parsed

register.si returns two formats; the script handles both:

**Slovenian text**
- `je prosta` → available
- `je rezervirana` / `je registrirana` → taken

**HTML**
- class `...reserved-domain` → taken
- class `...available-domain` → available

If the site changes its CSS class names, open the checker in your browser → F12 → Network → `admin-ajax.php` → Response, and add the new class to `classify_payload()`.

---

## Troubleshooting

**`DAS is banned` at startup**
Wait 1–2 hours, reboot your router for a new IP, or use a mobile hotspot. Verify:

```powershell
python -c "import socket; s=socket.create_connection(('das.arnes.si',4343),timeout=10); s.sendall(b'google.si\r\n'); print(repr(s.recv(1024)))"
```

`b'google.si is registered\n'` = working. `b''` = banned.

**Many `err` lines**
register.si is throttling you. Raise `--web-delay` to 5.0 or higher.

**HTTP 403 from register.si**
The nonce expired. The script refreshes it automatically. If it repeats, verify `FALLBACK_NONCE` matches the current value (F12 → Network → Request → `_ajax_nonce`).

**`pip` is not recognized**
```powershell
python -m pip install requests certifi
```

---

## Verify before buying

The script reports what ARNES says at the moment of the query. Availability changes by the minute. Cross-check any FREE result on:

- https://www.register.si/ (official checker)
- Your registrar (Dynadot, OVHcloud, INWX, Domenca)