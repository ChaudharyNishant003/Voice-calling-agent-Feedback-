# 05 — Dashboard & Notification Design

Audience: quality/patient-relations officers (daily users) and administrators (weekly users).
Design goals: **triage in seconds, evidence in one click, no training needed.** Staff resist yet another
dashboard, so the product also **pushes** (email digest + urgent alerts).

## 1. Design system

| Token | Value |
|---|---|
| Font | Inter (UI), JetBrains Mono (IDs, timestamps); Noto Sans Devanagari for Hindi verbatims |
| Base size | 14 px body, 12 px meta, 20/24 px headings |
| Spacing | 4-px grid (4, 8, 12, 16, 24, 32) |
| Radius | 8 px cards, 6 px inputs, 999 px pills |
| Colours (light) | bg `#F8FAFC`, surface `#FFFFFF`, text `#0F172A`, muted `#64748B`, border `#E2E8F0`, primary `#0F766E` (teal) |
| Priority | P1 `#DC2626` red, P2 `#D97706` amber, P3 `#475569` slate — **always paired with a text label**, never colour alone |
| SLA state | on-track `#16A34A`, due < 25% time left `#D97706`, breached `#DC2626` + icon |
| Dark mode | supported via CSS tokens (`prefers-color-scheme` + toggle) |
| Components | shadcn/ui: Table, Sheet, Dialog, Badge, Tabs, Command, Toast, Tooltip, Skeleton |
| Charts | Recharts; every chart has a table toggle ("View as table") for accessibility |
| Accessibility | WCAG 2.1 AA: contrast ≥ 4.5:1, full keyboard nav, focus rings, aria-labels, `lang="hi"` on Hindi text |
| Responsive | Desktop first (1280+), usable at 768 (tablet); queue + case detail usable on mobile (≥ 375) |

## 2. Navigation

Left sidebar (collapsible): **Queue** (default for quality) · Closure · Departments · Doctors ·
Locations · Operations · Data quality · Calls · Settings (admin).
Top bar: account/location switcher, date-range picker (persisted per user), global search
(`⌘K`: case ID, call ID, last-4 of phone, external patient ID), user menu.
Default landing: `quality`/`dept_owner` → Queue; `admin`/`read_only` → Closure.

## 3. Views (MVP — 8 + call detail + settings)

### 3.1 Escalation queue (landing)
```
┌ Queue ─────────────────────────────── [Mine | All] [P1 P2 P3] [Status ▾] [Dept ▾] ┐
│ Summary chips:  P1 open 2  ·  Breached 1  ·  Due < 2h 3  ·  Unassigned 4           │
├────┬──────┬──────────────────────────────┬────────────┬──────────┬────────┬───────┤
│Pri │ SLA  │ Summary (1 line)             │ Department │ Owner    │ Status │ Age   │
│ P1 │ 0:42 │ Reports mixed up with…       │ Radiology  │ —        │ Open   │ 18m   │
│ P2 │ 19h  │ Waited 3 hours at billing    │ Billing    │ R. Iyer  │ Assgnd │ 5h    │
└────┴──────┴──────────────────────────────┴────────────┴──────────┴────────┴───────┘
```
- Sort: priority ↑, then SLA remaining ↑. Breached rows pinned top with red left border.
- Row click → case detail in a right-side Sheet (keeps queue context). `j/k` to move, `a` acknowledge,
  `enter` open.
- Bulk actions: assign, acknowledge (not close).
- Auto-refresh every 30 s + toast on new P1 ("New P1 case in Radiology").

### 3.2 Case detail (Sheet / full page `/cases/{id}`)
Sections top→bottom:
1. Header: priority badge, status, SLA countdown (ack or resolve), owner, actions (Acknowledge ·
   Assign · Start · Resolve · Close · Reopen · Merge · Invalidate) — only valid transitions shown.
2. **Evidence card**: verbatim quote (Hindi rendered in Devanagari if spoken), timestamp,
   ▶ play clip (seeks to `verbatim_start_ms`, audited), "View full transcript".
3. Extracted facts: reason codes, sentiment, urgency (+ source: rule/LLM/human), department, doctor,
   visit date, respondent (patient/proxy), language.
4. Patient reference: external patient ID + phone last 4 only. Full number never shown in MVP.
5. Timeline: `case_events` (who, what, when), notes composer.
6. Resolve dialog: resolution note (min 20 chars, placeholder "What was done and was the patient
   contacted?"), `patient_contacted` checkbox.

### 3.3 Closure performance
KPI cards: Acknowledged within SLA % · Resolved within SLA % · Median time to acknowledge · Median time
to close · Open breaches · Reopen rate. Chart: weekly trend of the same. Table: by department/owner.

### 3.4 Department view
Table: dept · responses (n) · avg per dimension (1–5 or NPS) · complaints · top 3 reason codes · Δ vs
previous period (arrow + %). Click → dept drill: trend line, reason-code bar, recent verbatims (5).

### 3.5 Doctor view
Same as department, rows by doctor. **Minimum n = 5** before showing any score ("Not enough
responses yet"). Banner: "Scores reflect patient-reported experience, not clinical quality."

### 3.6 Location view
Same pattern; hidden when account has one location.

### 3.7 Call operations
Funnel: Visits ingested → Eligible → Attempted → Answered → Consented → Completed → With complaint.
Suppression breakdown donut (by reason, with counts). Answer rate by hour-of-day heatmap. Retry
outcomes. Live panel: calls in progress now / concurrency cap.

### 3.8 Data quality
Per batch: rows, invalid numbers %, duplicates, missing optional fields, unmapped departments (with
"Map" action), shared numbers under review (with Approve/Suppress). Message at top framed positively:
"Cleaner lists mean more patients reached."

### 3.9 Calls list + Call detail
List filters: status, language, safety flag, needs review. Detail: status timeline, consent state +
time, transcript (speaker-labelled, confidence shading < 0.6), audio player (if retained), extracted
fields table (value, confidence, method deterministic/LLM, source turn link), complaints, linked cases,
cost breakdown (admin), "Mark reviewed" for safety/low-confidence review queue.

### 3.10 Settings (admin)
Tabs: Account (window, days, holidays, caps, languages, proxy) · SLA · Retention · Departments & owners
· Locations · Users · Survey (version editor with JSON schema validation + preview/"Play audio") ·
Ingestion (SFTP details, template) · Suppression · Deletion requests · Audit log.
Every save shows a diff confirmation dialog for compliance-affecting fields (window, retention, caps).

## 4. States for every screen

| State | Pattern |
|---|---|
| Loading | Skeleton rows/cards; never spinner-only for > 300 ms |
| Empty | Illustration-free, one sentence + next action. e.g. Queue: "No open cases. New complaints will appear here automatically." |
| Partial data | Inline notice: "Some calls from today are still being processed." |
| Error (fetch) | Inline card with message from catalogue + "Try again"; request_id shown small for support |
| Permission | "You don't have access to this page. Ask your administrator." (never reveal data existence) |
| Stale | "Updated 2 min ago" + refresh button |
| Offline | Top banner: "You're offline. Changes will not be saved." — mutating buttons disabled |

All copy lives in `dashboard/src/i18n/en.json`; message keys match doc 06 catalogue.

## 5. Forms & validation UX

- Validate on blur + submit; server errors mapped to fields via `error.details.field`.
- Destructive/irreversible actions (invalidate P1, approve deletion, pause account) use a typed
  confirmation ("Type PAUSE to confirm").
- Optimistic update only for notes; state transitions wait for server (409 → "This case was updated by
  someone else. Reload to see the latest." with Reload button).

## 6. Email notifications (NotificationAdapter.send_email)

Plain, mobile-friendly HTML + text alternative. **No verbatims, no phone numbers, no patient names in
email** — only case ID, priority, department, reason label, SLA due, and a deep link (login required).

### 6.1 P1 urgent alert (immediate)
```
Subject: [P1 – Action within 1 hour] Safety concern reported – Radiology – CASE-7F3K
Body:
A patient reported a possible safety concern after a recent visit.
Department: Radiology · Reason: Report error · Received: 23 Sep, 11:42
Acknowledge by: 23 Sep, 12:42
[Open case]  (link)
You're receiving this because you are on the safety escalation list for <Hospital>.
```
Re-alert if not acknowledged at 30 min (to owner + quality lead) and at breach (to admin).

### 6.2 P2 new case (batched every 15 min per recipient)
Subject: `[P2] 3 new service cases need acknowledgement – <Hospital>`

### 6.3 Daily digest (08:30 account-local, to quality + admins)
Yesterday: calls completed, new cases by priority, breaches, top 3 reason codes, closure rate; list of
open P1/P2 with SLA. Link to Queue.

### 6.4 SLA breach
Subject: `[Breached] CASE-9A21 – acknowledgement overdue by 2h`.

### 6.5 Weekly summary (Monday 09:00, admins)
Scores by department with Δ, closure KPIs, suppression/data-quality summary.

Unsubscribe from digests allowed per user; **P1 alerts cannot be disabled** for users on the safety list.
Email idempotency key = `{template}:{case_id}:{event_id}` to prevent duplicates.

## 7. Demo mode (sales requirement: demo-able in 10 minutes)

`make seed-demo` creates "Demo Hospital" with 2 locations, 6 departments, 30 days of synthetic calls,
~40 cases across all states, Hindi and English verbatims (synthetic), and a pre-rendered test call the
presenter can trigger to their own allowlisted phone from Settings → "Place demo call".
