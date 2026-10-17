"""End-to-end test of the engine against the fake services in mock_services.py.

Usage: python e2e_test.py PATH_TO_THE_BINARY [--show-log]
Each scenario prints OK/FAIL; the script exits with code 1 if anything fails.
The binary under test is the real production binary: only its base URLs point at the fakes.
"""
import builtins, datetime as dt, email, email.policy, functools, json, os, shutil, subprocess, sys, tempfile, time, urllib.request

# Every file in UTF-8, on Windows too (where the default is cp1252).
open = functools.partial(builtins.open, encoding="utf-8")

BINARY = os.path.abspath(sys.argv[1])
BINARY_NAME = os.path.basename(BINARY)   # keeps the .exe on Windows
SHOW_LOG = "--show-log" in sys.argv      # print the engine's output for every run
HERE = os.path.dirname(os.path.abspath(__file__))
WORK = tempfile.mkdtemp(prefix="engine_e2e_")
TODAY = dt.date.today().isoformat()
failures = []

def check(condition, description):
    print(("  OK    " if condition else "  FAIL  ") + description)
    if not condition: failures.append(description)

def control(**kw):
    urllib.request.urlopen("http://127.0.0.1:8765/__control?" + "&".join(f"{k}={v}" for k, v in kw.items())).read()

def requests_received():
    path = os.path.join(WORK, "requests.jsonl")
    return [json.loads(line) for line in open(path)] if os.path.exists(path) else []

def clear_request_log():
    path = os.path.join(WORK, "requests.jsonl")
    if os.path.exists(path): os.remove(path)

def mailbox():
    d = os.path.join(WORK, "mailbox")
    return sorted(os.listdir(d)) if os.path.isdir(d) else []

def read_email(name):
    with open(os.path.join(WORK, "mailbox", name)) as f:
        return email.message_from_string(f.read(), policy=email.policy.default)

def clients():
    return {c["id"]: c for c in json.load(open(os.path.join(WORK, "clients.json")))}

def edit_client(client_id, **changes):
    data = json.load(open(os.path.join(WORK, "clients.json")))
    for c in data:
        if c["id"] == client_id: c.update(changes)
    json.dump(data, open(os.path.join(WORK, "clients.json"), "w"), ensure_ascii=False, indent=4)

def history():
    return set(json.load(open(os.path.join(WORK, "processed_reviews.json"))))

def last_metrics():
    return json.loads(open(os.path.join(WORK, "logs", "metrics.jsonl")).read().strip().split("\n")[-1])

def write_config(**changes):
    cfg = {
        "gemini_api_key": "fake-gemini-key", "serpapi_key": "fake-serpapi-key",
        "gemini_model": "gemini-3.8-flash", "search_language": "es", "search_country": "es",
        "sender_email": "engine@example.com", "email_password": "test password",
        "smtp_url": "smtp://127.0.0.1:2525", "smtp_tls": False,
        "delay_between_calls_ms": 0,
        "serpapi_base_url": "http://127.0.0.1:8765", "gemini_base_url": "http://127.0.0.1:8765",
    }
    cfg.update(changes)
    json.dump(cfg, open(os.path.join(WORK, "config.json"), "w"), indent=2)

def run(*args):
    # Launched from the filesystem root on purpose: imitates Task Scheduler (cwd = System32).
    started = time.time()
    p = subprocess.run([os.path.join(WORK, BINARY_NAME), *args], cwd=os.path.abspath(os.sep),
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180)
    print(f"  · engine {' '.join(args) or '(no arguments)'} → exit code {p.returncode} in {time.time() - started:.1f}s")
    if SHOW_LOG:
        for line in (p.stdout + p.stderr).splitlines():
            print("      │ " + line)
    return p

# ------------------------------------------------------------------------------------
shutil.copy(BINARY, os.path.join(WORK, BINARY_NAME))
# On Windows, vcpkg puts libcurl.dll, zlib1.dll... next to the .exe: it won't start without them.
for f in os.listdir(os.path.dirname(BINARY)):
    if f.lower().endswith(".dll"):
        shutil.copy(os.path.join(os.path.dirname(BINARY), f), WORK)
server = subprocess.Popen([sys.executable, os.path.join(HERE, "mock_services.py"), WORK],
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
server.stdout.readline()

try:
    write_config()
    # The clients start in the OLD (Spanish, v12) format, to prove it is migrated on save.
    common = dict(activo=True, email="owner@example.com", idioma="es", ultima_fecha_scan="2026-02-14",
                  instrucciones_ia="Contesta con tono cercano, amable pero profesional.")
    initial = [
        dict(common, id="CLI-001", nombre="Restaurante Trasgu", direccion="Bulevar José Prat 27A, Madrid",
             web="https://restaurantetrasgu.com/", place_id="ChIJfaS4158lQg0Rb7vhaCzAXJA",
             data_id="0xd42259fd7b8a47d:0x905cc02c68e1bb6f", termino_busqueda_auto="Trasgu Madrid",
             competidores=["ChIJ_wnBgeglQg0RJNdp_dsXr58", "ChIJFwAAAGQlQg0R-VhqKR9AGII"]),
        # No IDs and no competitors: forces discovery.
        dict(common, id="CLI-002", nombre="Restaurante Casa Manolo", direccion="Bulevar José Prat 9, Madrid",
             web="https://restaurante-casamanolo.com/", place_id="", data_id="", competidores=[], ultima_fecha_scan=""),
        dict(id="CLI-003", nombre="Bar Inactivo", activo=False, email="x@y.com", internal_note="do not delete"),
    ]
    json.dump(initial, open(os.path.join(WORK, "clients.json"), "w"), ensure_ascii=False, indent=4)

    print("\n[1] First run (working directory different from the executable's)")
    p = run()
    check(p.returncode == 0, "exits with code 0")
    check(len(mailbox()) == 2, f"2 emails sent (got {len(mailbox())})")
    cs = clients()
    check("CLI-003" in cs and cs["CLI-003"].get("internal_note") == "do not delete" and cs["CLI-003"]["active"] is False,
          "the inactive client is still in clients.json, with its own fields")
    check(cs["CLI-001"].get("termino_busqueda_auto") == "Trasgu Madrid", "fields the engine doesn't know are kept")
    check(cs["CLI-001"]["language"] == "es", "the old Spanish language field is kept")
    check("ultima_fecha_scan" not in cs["CLI-001"] and cs["CLI-001"]["name"] == "Restaurante Trasgu",
          "old Spanish field names are migrated to English on save")
    check(cs["CLI-002"]["place_id"] == "ChIJFwAAAGQlQg0R-VhqKR9AGII" and cs["CLI-002"]["data_id"], "CLI-002: place_id and data_id discovered")
    check(cs["CLI-001"].get("latitude") and cs["CLI-002"].get("longitude"), "GPS coordinates saved")
    check([x["name"] for x in cs["CLI-002"]["competitors"]] == ["Mesón El Roble", "Taberna La Encina"], "CLI-002: competitors chosen by the AI (with names)")
    check(cs["CLI-001"]["competitors"][1]["name"] == "Restaurante Casa Manolo", "old competitors stored as a bare ID get their name")
    check(all(c["last_scan_date"] == TODAY for c in (cs["CLI-001"], cs["CLI-002"])), "last_scan_date = today")
    h = history()
    check(h == {"e1bb6f-r1", "e1bb6f-redit", "e1bb6f-r2", "e1bb6f-r4", "6a58f9-r1", "6a58f9-redit", "6a58f9-r2"},
          f"history holds 7 reviews ({sorted(h)})")
    req = requests_received()
    check(not any(x["params"].get("next_page_token") == "must-never-be-requested" for x in req if x["kind"] == "serpapi"), "stops paginating at the cutoff date")
    check(any(x["params"].get("next_page_token") for x in req if x["kind"] == "serpapi"), "paginates with a token full of special characters")

    message = read_email(mailbox()[0])
    subject = str(message["subject"])
    check(subject == f"Informe de reputación: Restaurante Trasgu ({TODAY})", f"subject with accents correctly encoded: «{subject}»")
    html = message.get_content()
    check("&lt;script&gt;" in html and "<script>alert" not in html, "a malicious review arrives escaped in the HTML")
    check("<h3>Situación</h3>" in html and "```" not in html, "AI analysis included, without markdown fences")
    check("Stars only" not in html and "Muy antiguo" not in html, "star-only reviews and reviews before the cutoff are skipped")
    check("Editada: ahora mucho mejor." in html and "Buen cachopo" in html,
          "an edited review (old creation date, recent edit) neither is lost nor stops the reading")
    check("Ver en Maps" in html and "Restaurante Casa Manolo" in html, "competitor table with names")
    check(max(len(line) for line in open(os.path.join(WORK, "mailbox", mailbox()[0])).read().split("\n")) <= 998, "no SMTP line longer than 998 characters")
    check(len(os.listdir(os.path.join(WORK, "reports"))) == 2, "2 reports written to reports/")
    check(os.path.getsize(os.path.join(WORK, "logs", "engine.log")) > 0, "log written to logs/engine.log")
    m = last_metrics()
    check(m["serpapi_calls"] == sum(x["kind"] == "serpapi" for x in req), f"metrics: SerpApi calls match the requests received ({m['serpapi_calls']})")
    check(m["gemini_calls"] == sum(x["kind"] == "gemini" for x in req), f"metrics: Gemini calls match ({m['gemini_calls']})")
    check(m["reports_sent"] == 2 and m["emails_sent"] == 2 and m["new_reviews"] == 7, "metrics: 2 reports, 2 emails, 7 reviews")

    print("\n[2] Second run on the same day (default frequency: 7 days)")
    clear_request_log()
    p = run()
    check(p.returncode == 0 and len(mailbox()) == 2, "nothing new is sent")
    check(requests_received() == [], "not a single paid call")
    check(last_metrics()["serpapi_calls"] == 0, "metrics: 0 calls when nothing is due")
    check("next report in 7" in p.stdout, "the log says when the next report is due")

    print("\n[3] --force with no new reviews")
    clear_request_log()
    p = run("--force")
    req = requests_received()
    check(p.returncode == 0 and len(mailbox()) == 2, "no empty reports are sent")
    check(not any(x["engine"] == "google_maps" for x in req if x["kind"] == "serpapi"), "discovery is not repeated (IDs and GPS cached)")
    check(not any(x["kind"] == "gemini" for x in req), "no AI calls when there is nothing new")

    print("\n[4] Frequency boundary (7 days ago is due, 6 is not) + dry run")
    seven_days_ago = (dt.date.today() - dt.timedelta(days=7)).isoformat()
    edit_client("CLI-001", last_scan_date=seven_days_ago)
    edit_client("CLI-002", last_scan_date=(dt.date.today() - dt.timedelta(days=6)).isoformat())
    control(extra="1")   # one new review appears
    p = run("--no-email")
    check("CLI-002: next report in 1" in p.stdout and ">>> CLI-001" in p.stdout, "processes CLI-001 and leaves CLI-002 for tomorrow")
    check(len(mailbox()) == 2 and "e1bb6f-extra" not in history(), "--no-email sends nothing and marks nothing as processed")
    check(clients()["CLI-001"]["last_scan_date"] == seven_days_ago, "--no-email does not move the scan date")

    print("\n[5] AI down (503) with a new review → degraded report, still delivered")
    control(ai="fail")
    clear_request_log()
    p = run("--force", "--client", "CLI-001")
    check(p.returncode == 0 and len(mailbox()) == 3, "the report is delivered anyway")
    html = read_email(mailbox()[-1]).get_content()
    check("No disponible (fallo temporal de la IA)" in html and "No se pudo generar el análisis" in html, "the report says what is missing, with no raw error text")
    calls = [x for x in requests_received() if x["kind"] == "gemini"]
    check(len(calls) == 6, f"3 attempts per AI call (2 calls → {len(calls)})")
    m = last_metrics()
    check((m["gemini_retries"], m["gemini_failures"]) == (4, 2), f"metrics: 4 retries and 2 AI failures ({m['gemini_retries']}, {m['gemini_failures']})")

    print("\n[6] AI blocks its answer (no 'content') + SMTP down")
    control(ai="blocked")
    write_config(smtp_url="smtp://127.0.0.1:2599")
    p = run("--force", "--client", "CLI-002")
    check(last_metrics()["emails_failed"] == 1, "metrics: failed email counted")
    check(p.returncode == 2, "exit code 2 (error); v12 crashed with an exception here")
    check("6a58f9-extra" not in history(), "the review is not marked as processed if the email didn't arrive")

    print("\n[7] Everything works again → the pending review is recovered")
    control(ai="ok")
    write_config()
    p = run("--force", "--client", "CLI-002")
    check(p.returncode == 0 and len(mailbox()) == 4 and "6a58f9-extra" in history(), "delivered and recorded in the history")
    check("Correcto, sin más." in read_email(mailbox()[-1]).get_content(), "the report contains the recovered review")
    print("  · metrics of a weekly report (1 client, 1 new review):", json.dumps(last_metrics()))

    print("\n[8] The AI invents competitor IDs → fallback rule")
    control(ai="hallucinate")
    edit_client("CLI-002", competitors=[])
    p = run("--force", "--client", "CLI-002", "--no-email")
    names = [x["name"] for x in clients()["CLI-002"]["competitors"]]
    check(names == ["Mesón El Roble", "Taberna La Encina"], f"picks the closest above (4.3) and below (4.1): {names}")
    control(ai="ok")

    print("\n[9] Report language: English client")
    edit_client("CLI-001", language="en", last_scan_date="")
    os.remove(os.path.join(WORK, "processed_reviews.json"))
    clear_request_log()
    p = run("--force", "--client", "CLI-001")
    message = read_email(mailbox()[-1])
    html = message.get_content()
    check(str(message["subject"]) == f"Reputation report: Restaurante Trasgu ({TODAY})", f"English subject: «{message['subject']}»")
    check("Star distribution" in html and "Suggested reply:" in html and "View on Maps" in html and "<h3>Situation</h3>" in html,
          "English labels and an English analysis")
    check("Distribución" not in html and "Respuesta sugerida" not in html, "no Spanish labels left in an English report")
    calls = [x for x in requests_received() if x["kind"] == "gemini"]
    check(any(x["task"] == "analysis" and x["language"] == "en" for x in calls), "the analysis prompt asks for English")
    check(all(x["reply_in_review_language"] for x in calls if x["task"] == "reply"), "replies are asked in each review's language")

    print("\n[10] Configuration errors")
    write_config(gemini_api_key="wrong")
    edit_client("CLI-002", competitors=[])
    clear_request_log()
    p = run("--force", "--client", "CLI-002", "--no-email")
    m = last_metrics()
    check(m["gemini_retries"] == 0 and m["gemini_calls"] == m["gemini_failures"] == sum(x["kind"] == "gemini" for x in requests_received()) > 0,
          f"invalid key (403): every call fails once, no pointless retries ({m['gemini_calls']} calls, {m['gemini_retries']} retries)")
    write_config()
    open(os.path.join(WORK, "config.json"), "w").write("{ broken")
    check(run().returncode == 1, "malformed config.json → exit code 1 and a clear message")
    check(run("--unknown-option").returncode == 64, "unknown argument → prints the usage")
finally:
    server.terminate()

print(f"\nTest folder: {WORK}")
print("RESULT:", "ALL OK" if not failures else f"{len(failures)} FAILURE(S)")
sys.exit(1 if failures else 0)
