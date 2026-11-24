# CivicSense

AI agent for classifying, prioritizing, routing and scheduling citizen complaints.
One portal, two doors: a landing page lets people continue as a **citizen** (no account) or as an **officer**
(sign-in required). Both sides share one database.

## Setup
```
pip install -r requirements.txt
python modules/classifier.py        # retrain the model for your scikit-learn version (avoids a version warning)
python create_user.py --demo        # creates 'admin', 'officer' and 'crew' (crew PW-1) accounts; the passwords are shown ONCE
```
There are no built-in passwords: the demo ones are random and printed once (only hashes are stored, so they cannot be shown again).
`python create_user.py` creates an account with a password you choose. Lost a password?
`python create_user.py --reset admin` sets a new one (and unlocks the account).

## Run
```
streamlit run app.py
```
Choose **Continue as city staff**, sign in as `admin`, open **Admin**, and click **Load demo data** (60 complaints). Then try
**Simulate monsoon surge** and watch the **Crew schedule** cope with 40 extra drainage complaints.
Leaving the officer portal (Back to home) signs the officer out, so nobody can walk into an open session.
The two portals can also be run alone: `streamlit run public_app.py` and `streamlit run officer_app.py`.

## What was added most recently
- **Model evaluation** (officer page *Model performance*): seven models compared on the easy synthetic test and on 82 hand-written
  hard cases, with a do-nothing baseline, confusion matrices and a list of mistakes. `python modules/evaluate.py` re-creates it.
- **Closing the loop:** the citizen sees a status history, the crew's note and an after photo, and can say "not fixed", which
  reopens the complaint and raises its priority. Officers see satisfaction and reopen rates on *Insights*.
- **Protecting people and the system:** phone numbers, e-mail addresses and ID numbers typed into a complaint are masked before
  saving; spam is refused or held for an officer; one visitor (and everyone together) is rate limited; photo metadata (camera,
  date, GPS) is stripped and uploads are re-encoded.
- **Field crews:** a crew account signs in through the staff door and sees only its own route on a phone-friendly page; it starts
  a job and finishes it with a note and an after photo. A crew account cannot open any officer page.

## What the interface offers
- **Landing page** with the two doors and live city figures.
- **Citizen:** pick the exact location (map pin, device location, coordinates or ward), example chips, a **live AI preview**
  while typing (category and department, nothing saved), photo upload, a tracking code with a progress tracker, a city dashboard.
- **Officer:** an attention panel (critical, waiting for review, open 7+ days), a clickable complaint queue with filters,
  the numbered "why this decision" trace, a crew timeline, a **hotspot map on a real street map of Chennai** (density glow,
  schools, hospitals and public places, filters, ward ranking; plus a schematic view that works offline), a **priority guide**,
  fairness chart, audit log, admin tools. Citizens get a ward-level map (totals only, never exact places).

## The street map
The hotspot map is a small web page (Leaflet, loaded from unpkg.com) shown inside the app, so it needs **no extra Python
package**, only an internet connection for the Leaflet code and the map tiles (CARTO light map, OpenStreetMap as an alternative:
use the layer button on the map). Without internet the app shows the schematic view instead. The demo complaints have coordinates
that fall in Chennai (roughly the Guindy-Saidapet area), but the wards, places and streets are fictional: replace
`data/places.yaml` with real places, and regenerate or replace the complaints, to make the demo match a real locality.

## How priority works near schools and public places
The AI first judges how serious a problem is. Rules (`rules/rules.yaml`) then look at **where** it is, using the words in the
complaint **and** the pin: anything within 150 m of a place in `data/places.yaml` counts as near it.
- **School or hospital:** routine problems become at least *high*; a dangerous problem (open manhole, live wire, ...) is *critical*.
- **Busy public place** (market, bus stand, railway station, temple, park): the same, so a crowd is treated like a school.
- Among complaints of the same priority, the **score** orders them: near a school/hospital +15, near a public place +8.
- Street names do not count ("Temple Street" is not a temple). The officer **Priority guide** page shows the full table and
  lets you try combinations; every cell comes from running the real rule engine. Replace `data/places.yaml` with your real places.

## Who can see what
| | Citizen portal (no login) | Officer | Admin |
|---|---|---|---|
| Report a complaint (text, location, photo) | yes | | |
| Check the status of **their own** complaint with a tracking code | yes (status only) | | |
| City-wide totals and a ward-level map (wards with fewer than 3 complaints hidden; no exact places) | yes | yes | yes |
| Complaint text, photos, exact locations, reasoning traces, schedules, maps | **never** | yes | yes |
| Review and correct, resolve | | yes | yes |
| Create accounts, load demo data, reset, export corrections, audit log | | | yes |

Security measures: passwords stored only as salted scrypt hashes; the same error for a wrong password and an unknown
user; accounts lock for 5 minutes after 5 failed attempts; sessions expire after 30 minutes; the role is re-read from the
database on every page load (deactivating an account takes effect immediately); every sign-in and officer action is
written to an audit log; uploads are accepted only if the file contents are a JPEG or PNG (max 5 MB) and are saved
under our own file names; all user text is HTML-escaped; tracking codes are random (`CS-XXXXXXXX`), not complaint numbers.

## Choosing the location
The report page offers four ways: **pin on the map** (click), **use my current location**, **type coordinates**, or
**pick a ward**. The first two need `folium`, `streamlit-folium` and `streamlit-geolocation` (in requirements.txt); if they
are missing, those options explain what to install and the other two still work. Any location outside the service area
(`SERVICE_AREA` in `modules/geo.py`) is refused. The demo "city" (wards, streets, road network, crews) is fictional;
its coordinates are only a placeholder range.

## Where the data is stored
Everything is in a SQLite database, `civicsense.db`, created in the project folder on first run. Tables: `complaints`,
`corrections` (officer corrections), `users` (accounts: hashes only), `audit_log`. Uploaded photos are files in `uploads/`.
Open the database with "DB Browser for SQLite" to look inside. Older databases are upgraded automatically. **Reset database**
deletes complaints and photos but keeps accounts and the audit log.

## Project layout
| Part | Files |
|---|---|
| Module 1: classify + priority + duplicates | `modules/classifier.py`, `modules/duplicates.py` |
| Module 2: rule engine (forward chaining) | `modules/rule_engine.py`, `rules/rules.yaml`, `rules/wards.yaml` |
| Module 3: CSP + A* scheduler | `modules/scheduler.py`, `data/crews.yaml` |
| Engine + database | `pipeline.py`, `database.py` |
| Accounts and permissions | `auth.py`, `create_user.py` |
| Landing page and routing | `app.py` |
| Citizen portal | `public_app.py`, `location_picker.py` |
| Officer portal | `officer_app.py` |
| Shared look (icons, cards, charts) | `ui.py`, `app_common.py`, `.streamlit/config.toml` |
| Places and priority guide | `modules/places.py`, `data/places.yaml`, `modules/guide.py` |
| Data | `data/generate_dataset.py` -> `data/complaints.csv` |

## Tests
```
python tests/test_rule_engine.py     # 22 tests (rules, places, ranking)
python tests/test_places.py          # 6 tests (places file, nearby search, priority guide)
python tests/test_scheduler.py       # 11 tests
python tests/test_pipeline.py        # 33 tests (database, duplicates, photos, tracking codes, public views, audit, places, hotspots)
python tests/test_auth.py            # 15 tests (passwords, lock-out, roles, sessions, reset)
python tests/test_workflow.py        # 30 tests (privacy, spam, rate limits, photos, status history, feedback, reopen, crews)
python tests/test_evaluate.py        # 12 tests (model comparison, confusion matrices, baseline)
python tests/test_ui.py              # 27 tests (visual components, maps, icons, HTML escaping)
python tests/test_leaflet_js.py      # 6 tests: the map pages run in a real browser against a stand-in for Leaflet
                                     # (skipped automatically if Playwright is not installed)
python tests/ui_smoke_test.py        # 168 checks: landing page and both portals against a stand-in for Streamlit
```
The smoke test checks what each visitor can see (the landing page and citizen pages never show a complaint; the officer
portal shows nothing until sign-in, enforces roles and sessions, and signs out on leaving). It cannot check how pages look in the real app, and it uses stand-ins for
the optional map libraries, so it proves our logic, not those libraries' real behaviour.

## Scripts
```
python demo.py                       # Module 1 -> 2 with reasoning traces
python demo_schedule.py 3            # one sample day's schedule
python compare_baseline.py 30 45     # CivicSense vs first-come-first-served over 30 simulated days
```
Edit `rules/rules.yaml` to change routing or priority rules, and `data/crews.yaml` for crews. No code changes needed.

## Results
- Module 1, easy synthetic test: category ~98%, priority ~86%. These are flattering: the data was made from templates.
- Module 1, **82 hand-written hard cases** (typos, shorthand, Tanglish; labelled by the team): live model (Logistic Regression) category
  **77%** (plus or minus about 9 points), priority exact **48%**.
  The do-nothing baseline gets 23% on category, so the model does learn.
  Unclear complaints are sent to a person 89% of the time, but so are
  27% of clear ones: the cost of being careful.
- Best model on the hard cases: category Linear SVM (78%), priority Random Forest
  (55%). With this few cases, differences of a few points are within the noise.
  The live system chooses between Logistic Regression and Decision Tree using the easy test only.
- "Priority within one level" looks good (about 83%) but always guessing the most common priority scores the same, so it is not
  evidence of skill. Use exact accuracy and macro-F1.
- Duplicate detection (similarity >= 0.40 and within 100 m): precision 0.90, recall 0.84.
- Module 2 adds safety guarantees, place-aware ranking and explanations; on the hard cases it changes exact priority only slightly
  (48% -> 49%): its value is safety and explainability, not accuracy.
- Module 3 vs first-come-first-served (simulated days, same crews, same complaints):

  | complaints/day | urgent on time (FCFS -> CivicSense) | critical mean wait (min) |
  |---|---|---|
  | 30 | 91% -> 100% | 97 -> 59 |
  | 45 | 83% -> 98% | 123 -> 73 |
  | 60 | 72% -> 93% | 139 -> 87 |

## Limits to state honestly
- The city, road network, crews, service times, deadlines and ward populations are synthetic assumptions.
- The login is suitable for a course project. A real deployment also needs HTTPS, a proper identity provider
  (single sign-on), server-level rate limiting, and the officer portal on an internal network.
- The tracking-code lookup limit is per browser session; a real deployment would limit per IP address.
- The CSP search has a node budget; a job that does not fit is scheduled late, not dropped.
- The fairness rule only applies once 30+ complaints exist (ward shares are too noisy before that).
- Hazard detection uses keyword patterns and will miss unusual wording. The places in `data/places.yaml` are fictional;
  the rules only know about places listed there (or named in the complaint text).
- Rate limiting is per browser session plus a global cap; a determined person opening new sessions can bypass the per-visitor
  limit. Masking recognises Indian phone and ID formats and will miss others; the spam checks are simple rules, not a model.
- Feedback is tied to a tracking code, so anyone holding the code can answer for that complaint.
- Crew accounts are only as safe as their passwords; there is no device check. Route changes can move a job to another crew
  until it is started (after that it is pinned to the crew that started it).
- The hard cases and their labels were written by the team: add your own and re-run the evaluation.
- Text is English-only. Tamil/Tanglish complaints failed on the hard cases, so multilingual support is future scope.
- A photo is stored and shown to officers as evidence. The AI does not analyse it (image analysis is future scope).
- With both portals in one app, the officer pages are protected only by the sign-in check, which runs on every page load
  (it is tested, including deliberate breakages). Two separately deployed apps would separate them more strongly.
- The map libraries and the dashboards were tested with stand-ins, not inside real Streamlit, before being handed over.
  The street-map page was tested against a stand-in for Leaflet, so our code is checked but Leaflet's own drawing and the
  tile servers are not. Loading Leaflet from unpkg.com means trusting that site; for a real deployment, host Leaflet yourself.
  The inline SVG icons and the animations were checked in a real browser, but not inside Streamlit.
