# Reputation Engine

An unattended C++ pipeline that watches the Google Maps reviews of a portfolio of small
businesses and, on each business's own schedule, emails the owner a report with:

- the new reviews and an **AI-drafted reply** for each one,
- headline numbers (Google rating, star distribution, positive / neutral / negative),
- a **comparison with two nearby competitors** (one slightly better, one equal or worse),
- a **strategic analysis** written by the AI, ending with one concrete action for the week.

Stack: C++17 · libcurl (HTTP and SMTP) · nlohmann/json · SerpApi (Google Maps data) · Gemini (LLM).

Each client's `language` (`"en"` or `"es"`) sets the language of its report, the AI
analysis and the email subject. Suggested replies are written in the language of each
review, so a tourist who writes in English gets an English reply.

---

## 1. How a run works

```
Task Scheduler (once a day)
        │
        ▼
main ── parses options ── finds its own folder (the .exe's) ── opens logs/engine.log
        │
        ├─ config.json              (keys, or MOTOR_* environment variables)
        ├─ clients.json             (ALL clients, inactive ones too)
        └─ processed_reviews.json   (IDs of reviews already reported)
        │
        ▼
For each active client:
  have `frequency_days` passed since `last_scan_date`?  ── no ──► "next report in N day(s)"
        │ yes
        ▼
  1. discover_place_ids      place_id, data_id and GPS (SerpApi google_maps) – first run only
  2. download_reviews        newest first, paginating until the cutoff date
  3. choose_competitors      only if it has none: searches its category in a neighbourhood
                             radius (ll=@lat,lng,15z) and the AI picks motivator + rival;
                             invalid or invented IDs → deterministic rule by rating
     └─ save clients.json    (what was discovered is never paid for again)
  4. dedupe against history  nothing new? → update the date and move on (no email)
  5. suggest_reply           one Gemini call per review
  6. competitor data         one page of reviews + rating for each competitor
  7. consultant analysis     one Gemini call with everything above
  8. render_report           email-safe HTML → reports/CLI-XXX_YYYY-MM-DD.html
  9. send_email              SMTP (Gmail)
 10. ONLY if the email was accepted: reviews → history, last_scan_date = today
     └─ save clients.json + history (atomic writes)
        │
        ▼
Metrics line · exit code 0 (all good) / 2 (a client failed) / 1 (config error) / 64 (bad arguments)
```

### Scheduling
Each client's `frequency_days` (default 7) decides how often it gets a report. The
executable is scheduled **once a day** and decides by itself who is due, so one task
serves weekly, fortnightly and daily clients alike.

On Windows (no need to fill "Start in": the engine finds its files next to the .exe):

```bat
schtasks /Create /TN "ReputationEngine" /TR "\"C:\Engine\ReputationEngine.exe\"" /SC DAILY /ST 08:45
```

On Linux: `45 8 * * * /opt/engine/ReputationEngine`.

### Options
| Option | Meaning |
|---|---|
| `--force` | ignore each client's frequency |
| `--client CLI-001` | process only that client |
| `--no-email` | dry run: write the reports, send nothing, mark nothing as processed |
| `--dir PATH` | working folder other than the executable's |

### Run metrics
At the end of every run the engine appends one JSON line to `logs/metrics.jsonl`:

```json
{"date":"2026-10-10T08:30:10","duration_ms":50,"reports_sent":1,"no_news":0,"not_due":0,"errors":0,
 "new_reviews":1,"serpapi_calls":4,"serpapi_errors":0,"gemini_calls":2,"gemini_retries":0,
 "gemini_failures":0,"emails_sent":1,"emails_failed":0}
```

It answers "how much did this run cost?" (paid calls) and "is something degrading?"
(retries, failures). JSON lines can be ingested as-is by any log agent.

---

## 2. Files

| File | What it is |
|---|---|
| `src/reputation_engine.cpp` | the whole program, in 8 numbered sections |
| `config.json` | keys and settings (see `config.example.json`). **Never commit it.** |
| `clients.json` | client registry (see `clients.example.json`) |
| `processed_reviews.json`, `reports/`, `logs/` | created by the engine |
| `tests/` | fake services + end-to-end test |

Older Spanish file and field names (`clientes.json`, `historial_procesados.json`,
`ultima_fecha_scan`, `email_remitente`, ...) are still read and are migrated to the
English names the first time the registry is saved. Fields the engine doesn't know are kept.

Secrets can come from environment variables (`MOTOR_GEMINI_API_KEY`, `MOTOR_SERPAPI_KEY`,
`MOTOR_EMAIL_PASSWORD`), which take priority over `config.json`.

---

## 3. Build

```bat
vcpkg install curl:x64-windows nlohmann-json:x64-windows
cmake -B build -DCMAKE_TOOLCHAIN_FILE=C:/vcpkg/scripts/buildsystems/vcpkg.cmake
cmake --build build --config Release
```

Or a Visual Studio "Empty Project" with `src/reputation_engine.cpp`, C++17, `/utf-8`,
and `_CRT_SECURE_NO_WARNINGS` defined.

## 4. Test without spending credits

```bash
python tests/e2e_test.py path/to/ReputationEngine[.exe] [--show-log]
```

It starts fake SerpApi, Gemini and SMTP servers on localhost and runs the **real binary**
through 10 scenarios with 54 assertions: first run, idempotent re-run (zero paid calls),
frequency boundary, dry run, AI down / blocked / inventing IDs, SMTP down and recovery,
invalid key, broken config, HTML escaping, header encoding, pagination, legacy field
migration, report language, edited reviews, and that the metrics match the requests the fakes actually received.

---

## 5. What changed from v12

**Data loss / wrong behaviour**
1. Inactive clients were **deleted** from the registry: only active ones were loaded, then the file was rewritten from that list.
2. `ultima_fecha_scan` was saved but **never read**, so every run looked 30 days back.
3. GPS coordinates were never saved, so discovery ran (and was paid for) on every run.
4. The "nothing new" exit was commented out: an **empty report** (and AI calls) every time.
5. Reviews were marked as processed **before** the email was sent: a failed email lost them.
6. Competitor selection got rating, review count and type **as 0**, and our own rating **hard-coded to 4.0**; returned IDs were not validated.
7. There was no per-client frequency: every run processed everyone.

**Crashes and corrupted output**
8. A blocked Gemini answer (no `content`) threw an uncaught `json::type_error` and **killed the run**.
9. `ERROR_TIMEOUT` was not treated as an error, so that string **appeared in the report** as the reply.
10. Errors were detected with `find("Error")`, with false positives on legitimate replies.
11. Review text was inserted into the HTML **unescaped** (broken layout / XSS).
12. Email lines longer than 998 characters (SMTP limit) and an unencoded accented subject (RFC 2047).
13. Charts used Chart.js, but **email clients don't run JavaScript**: they arrived blank.
14. CSS classes used but never defined.
15. A made-up Maps link for hexadecimal IDs; competitors shown as raw IDs.
16. Launched from Task Scheduler, the working directory is `System32`, so `config.json` was **not found**.
17. `std::cin.get()` and `Sleep(5000)` blocked or delayed unattended runs.

**Security**
18. TLS verification **disabled** on every request, including the SMTP login.
19. The Gemini key travelled in the URL; now in the `x-goog-api-key` header.
20. URL parameters were not encoded (pagination tokens, `data_id` with `:`).
21. Reviews went into prompts as-is (prompt injection); now fenced and declared as data.
22. Keys and passwords in plain text in `config.json` and in a PowerShell script.

**Clean-up**
23. Over a third of the file was commented-out code, plus unused functions.
24. Three different HTTP code paths (raw curl, `cpr`, a helper) → one.
25. An extra SerpApi call per competitor and run to "convert" `place_id` to `data_id`, unnecessary.
26. Windows-only code (`Sleep`, `_mkdir`, `winsock2.h`) → portable `<thread>` and `<filesystem>`.
27. Comments contradicting the code.
28. Leftover files from older versions (`datos.csv`, `enviar_correo.ps1`).
29. Identifiers, logs and configuration translated to English; report language configurable per client.
30. Found on the first live run: an edited review keeps its original `iso_date`, so the engine stopped reading at it and missed newer reviews. It now uses the later of creation and edit date, and an old review no longer stops the page.

---

## 6. Known limitations / next steps

- **"Based on the website"**: Gemini does not visit URLs on its own. List the real dishes in
  `ai_instructions`, or try `"gemini_web_search": true` (Gemini's `google_search` tool; not verified against the live API).
- Dates are compared as `YYYY-MM-DD` strings, so a hand-edited date must be well-formed; they should be validated on load.
- `sanitize_ai_html` is a blocklist; production should use an allowlist sanitizer.
- Fixed retry delays (2 s, 4 s): exponential backoff with jitter and `Retry-After` would be better.
- The history grows forever; with many clients, a database (SQLite) with a date per review.
- Clients run sequentially; parallelising needs a worker pool under the APIs' rate limits and a
  single writer for shared state (history, registry, metrics, log).
- No run lock: overlapping runs rely on Task Scheduler's "do not start a new instance".
- Gmail limits daily sends; many clients need a transactional email provider.
