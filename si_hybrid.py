#!/usr/bin/env python3
"""
Hybrid .si domain checker.
  Phase 1: ARNES DAS (port 4343, fast) — until banned
  Phase 2: register.si AJAX (HTTPS, slow) — until 429 or done

Writes each FREE domain to the CSV immediately (survives crash/Ctrl+C).

Requires: pip install requests certifi
"""

import argparse, csv, os, re, socket, sys, threading, time
import requests

DAS_HOST, DAS_PORT, DAS_TIMEOUT = "das.arnes.si", 4343, 10
AJAX_URL = "https://www.register.si/wp-admin/admin-ajax.php"
CHECKER  = "https://www.register.si/"
HTTP_TIMEOUT = 20

DAS_DELAY       = 1.0
WEB_DELAY       = 3.0
BAN_PROBE_EVERY = 50
FALLBACK_NONCE  = "59ca958c14"

_lock = threading.Lock()
_last_len = 0


def progress(phase, done, total, free, err, taken, extra=""):
    global _last_len
    pct = (done / total * 100) if total else 0
    line = (f"\r[{phase}] [{done}/{total}] {pct:5.1f}%  "
            f"FREE: {free}  taken: {taken}  err: {err} {extra}")
    pad = max(0, _last_len - len(line))
    sys.stdout.write(line + " " * pad)
    sys.stdout.flush()
    _last_len = len(line)


def event(text):
    global _last_len
    sys.stdout.write("\r" + " " * _last_len + "\r" + text + "\n")
    sys.stdout.flush()
    _last_len = 0


# ---------- incremental CSV writer ----------

_free_fp = None

def open_free_csv(path, reset=False):
    global _free_fp
    if reset and os.path.exists(path):
        os.remove(path)
    new = not os.path.exists(path)
    _free_fp = open(path, "a", newline="", encoding="utf-8")
    if new:
        w = csv.writer(_free_fp); w.writerow(["domain"]); _free_fp.flush()

def write_free(domain):
    if _free_fp is None:
        return
    with _lock:
        w = csv.writer(_free_fp)
        w.writerow([domain])
        _free_fp.flush()       # flush to disk immediately
        os.fsync(_free_fp.fileno())

def close_free_csv():
    global _free_fp
    if _free_fp:
        _free_fp.close()
        _free_fp = None


# ---------- wordlist ----------

def fetch_wordlist(source):
    if source.startswith(("http://", "https://")):
        event(f"Downloading {source} ...")
        r = requests.get(source, timeout=30, headers={"User-Agent": "si/12"})
        r.raise_for_status()
        text = r.text
    else:
        with open(source, encoding="utf-8", errors="ignore") as f:
            text = f.read()
    words, seen = [], set()
    for line in text.splitlines():
        w = line.strip().lower()
        if re.fullmatch(r"[a-z]{4,8}", w) and w not in seen:
            seen.add(w); words.append(w)
    return words


# ---------- Phase 1: DAS ----------

def das_query(domain):
    try:
        with socket.create_connection((DAS_HOST, DAS_PORT), timeout=DAS_TIMEOUT) as s:
            s.settimeout(DAS_TIMEOUT)
            s.sendall((domain + "\r\n").encode("ascii"))
            buf = b""
            while b"\n" not in buf:
                d = s.recv(1024)
                if not d:
                    break
                buf += d
        return buf.decode("utf-8", errors="replace").strip()
    except Exception:
        return None


def das_classify(raw):
    if raw is None:  return "unknown"
    if raw == "":    return "banned"
    low = raw.lower()
    if "is registered" in low:  return "registered"
    if "is available" in low or "is not registered" in low or "is free" in low:
        return "available"
    return "unknown"


def das_test():
    st = das_classify(das_query("google.si"))
    if st == "registered": return "ok"
    if st == "banned":     return "banned"
    return "error"


# ---------- Phase 2: register.si AJAX ----------

def make_session():
    s = requests.Session()
    s.headers.update({
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:158.0) "
                       "Gecko/20100101 Firefox/158.0"),
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "X-Requested-With": "XMLHttpRequest",
        "Origin": "https://www.register.si",
        "Referer": "https://www.register.si/",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    })
    try:
        s.get(CHECKER, timeout=HTTP_TIMEOUT)
    except Exception:
        pass
    return s


def get_nonce(session):
    try:
        r = session.get(CHECKER, timeout=HTTP_TIMEOUT)
        m = re.search(r'_ajax_nonce["\']?\s*[:=]\s*["\']([a-f0-9]{8,12})["\']', r.text)
        if m:
            return m.group(1)
    except Exception:
        pass
    return FALLBACK_NONCE


def _has_any(text, *needles):
    low = text.lower()
    return any(n in low for n in needles)


def classify_payload(raw):
    """
    Given the raw response body (text or HTML), return
    'available', 'registered', or 'unknown'.
    """
    if not raw:
        return "unknown"
    low = raw.lower()

    # ---------- HTML class hints (strongest signal) ----------
    if _has_any(low,
                'class="whois__results-panel reserved-domain',
                "class='whois__results-panel reserved-domain",
                "reserved-domain",
                "registered-domain",
                "taken-domain",
                "is-reserved",
                "is-registered"):
        return "registered"

    if _has_any(low,
                'class="whois__results-panel available-domain',
                "class='whois__results-panel available-domain",
                "available-domain",
                "free-domain",
                "is-available",
                "is-free"):
        return "available"

    # ---------- Slovenian plain text ----------
    if _has_any(low, "je prosta", "je prost", "je na voljo", "ni rezervirana"):
        return "available"
    if _has_any(low, "je rezervirana", "je registrirana", "je zasedena",
                "ni na voljo", "je že registrirana"):
        return "registered"

    # ---------- English fallbacks ----------
    if _has_any(low, "is available", "is free", "not registered"):
        return "available"
    if _has_any(low, "is taken", "is registered", "not available"):
        return "registered"

    return "unknown"


def ajax_check(session, domain, nonce):
    """
    Returns (status, http_code, raw).
    status: available / registered / unknown / ratelimited
    """
    data = {
        "_ajax_nonce": nonce,
        "action": "get_domain_status",
        "domain": domain,
    }
    try:
        r = session.post(AJAX_URL, data=data, timeout=HTTP_TIMEOUT)
    except Exception as e:
        return "unknown", None, f"{type(e).__name__}: {e}"

    if r.status_code == 429:
        return "ratelimited", 429, r.text[:200]
    if r.status_code == 403:
        return "unknown", 403, r.text[:200]
    if r.status_code != 200:
        return "unknown", r.status_code, r.text[:200]

    raw = r.text
    st = classify_payload(raw)
    return st, 200, raw.strip()[:300]


# ---------- main ----------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("wordlist")
    ap.add_argument("--out", default="available_si.csv")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--das-delay", type=float, default=DAS_DELAY)
    ap.add_argument("--web-delay", type=float, default=WEB_DELAY)
    ap.add_argument("--phase", choices=["auto", "das", "web"], default="auto")
    ap.add_argument("--reset", action="store_true",
                    help="wipe the CSV and start fresh")
    args = ap.parse_args()

    open_free_csv(args.out, reset=args.reset)
    event(f"Writing FREE domains to {args.out} (incrementally)")

    words = fetch_wordlist(args.wordlist)
    if args.limit:
        words = words[:args.limit]
    total = len(words)
    event(f"Loaded {total} candidates.\n")

    counts = {"available": 0, "registered": 0, "unknown": 0}
    done = 0
    das_dead = False

    if args.phase == "web":
        phase = "web"; das_dead = True
        event("Forced web phase.")
    elif args.phase == "das":
        phase = "das"
    else:
        event("Probing DAS ...")
        probe = das_test()
        if probe == "ok":
            event("DAS is alive. Starting fast phase.")
            phase = "das"
        else:
            event(f"DAS is {probe}. Starting web phase.")
            phase = "web"; das_dead = True

    session = None
    nonce = None

    def ensure_web():
        nonlocal session, nonce
        if session is None:
            session = make_session()
            nonce = get_nonce(session)
            event(f"Using nonce: {nonce}")

    try:
        while done < total:
            word = words[done]
            domain = word + ".si"

            if phase == "das":
                time.sleep(args.das_delay)
                st = das_classify(das_query(domain))

                if st == "banned":
                    event("⚠  DAS banned — switching to register.si (slow)")
                    phase = "web"; das_dead = True
                    ensure_web()
                    continue
                if st == "unknown":
                    counts["unknown"] += 1
                    done += 1
                    progress("DAS", done, total, counts["available"],
                             counts["unknown"], counts["registered"])
                    continue

                counts[st] += 1
                done += 1
                if st == "available":
                    write_free(domain)
                    event(f"FREE      {domain}   -> saved to {args.out}")
                progress("DAS", done, total, counts["available"],
                         counts["unknown"], counts["registered"])
                continue

            # ---- web phase ----
            ensure_web()
            time.sleep(args.web_delay)

            st, code, raw = ajax_check(session, domain, nonce)

            if st == "ratelimited":
                event("✗ HTTP 429 from register.si — stopping.")
                break

            if st == "unknown" and code == 403:
                event("403 — refreshing nonce and retrying ...")
                try:
                    nonce = get_nonce(session)
                    st, code, raw = ajax_check(session, domain, nonce)
                except Exception as e:
                    event(f"  refresh failed: {e}")

            if st == "ratelimited":
                event("✗ HTTP 429 after retry — stopping.")
                break

            if st == "unknown":
                counts["unknown"] += 1
                event(f"ERROR     {domain}  (code={code})")
            else:
                counts[st] += 1
                if st == "available":
                    write_free(domain)
                    event(f"FREE      {domain}   -> saved to {args.out}")

            done += 1
            progress("WEB", done, total, counts["available"],
                     counts["unknown"], counts["registered"])

            if das_dead and done % BAN_PROBE_EVERY == 0:
                if das_test() == "ok":
                    event("✓ DAS is back — switching to fast phase")
                    phase = "das"; das_dead = False

    except KeyboardInterrupt:
        event("Interrupted — CSV already saved up to here.")

    sys.stdout.write("\n")
    close_free_csv()

    print(f"\n================ SUMMARY ================")
    print(f"  Checked:    {done}/{total}")
    print(f"  FREE:       {counts['available']}")
    print(f"  registered: {counts['registered']}")
    print(f"  errors:     {counts['unknown']}")
    print(f"  Free ->  {args.out}")
    print("=========================================")


if __name__ == "__main__":
    main()