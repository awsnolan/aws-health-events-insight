# Backlog

Follow-ups for the issue-focused HEIDI fork. The build is deployed and usable;
these are the known tweaks and gaps. Priority is rough, top-to-bottom within each
section.

## Requested

1. **Fix panel ordering (issue/SLA analysis).**
   The `GridLayout` in `HealthModuleIssueQSAnalysis.yaml` currently flows KPIs →
   downtime-by-service + by-region → per-service bar → detail table. The
   per-service bar lands awkwardly directly above the detail table. Decide a
   deliberate reading order (e.g. KPIs, then the three bars grouped, detail table
   last) and set it via the `Layouts` `Elements` order / `ColumnIndex`/`RowIndex`.

2. **[DONE] Output mode: CSV/JSON to S3 instead of QuickSight.**
   Implemented as the `OutputMode` parameter (`s3` | `quicksight` | `both`,
   default `s3`). `s3` deploys only the scheduled `S3ExtractModule` Lambda and
   skips every QuickSight resource (datasource, datasets, analyses, and the
   `AthenaQuicksightAssumeRole`). The core `awshealthevent` Glue table was moved
   from `HealthModuleDataSetSetup.yaml` into `DataCollectionModule.yaml` so it
   exists independent of QuickSight — that decoupling is what makes the lean
   ~16-resource S3-only footprint possible. Replaces the old
   `EnableIssueDashboards`/`EnableS3Extract` toggles. See FORK-NOTES.md.

3. **Relabel panels — neutral vocabulary.**
   Remove presumptive/loaded terms: avoid "credit" (don't presuppose a credit
   will be pursued) and "outage". Settle on neutral language (e.g. "service
   event" / "service impact" / "service health event") and apply consistently
   across: analysis visual titles, KPI narratives, and the ticketing module's
   user-facing strings. Note the module/stack is named `CreditModule` and the
   Jira ticket text says "SLA service credit" — fold those into the same rename.

4. **Jira wiring — finish and validate end to end.**
   The credit/ticketing module is written and opt-in but not yet deployed or
   tested. To close out:
   - Create the `heidi-jira` secret; deploy with `EnableCreditModule=yes`.
   - Verify ticket create + idempotent update (re-emitted events comment, not
     duplicate), 429 retry/backoff, and DLQ capture on failure.
   - Confirm the `issue` EventPattern matches both real-time and backfilled
     events.
   - Decide ticket **grain** (per event vs per account vs per entity) — at 500+
     accounts a single public event could fan out to hundreds of tickets.
   - Add volume scoping (`eventScopeCode = PUBLIC`, severity) to avoid Jira
     flood.
   - Apply the neutral vocabulary from item 3.

## Additional (identified during the build)

### Dashboard / analysis
- **Relative-date control:** swap the absolute `DATE_RANGE` picker for a
  `RelativeDatesFilter` + `RelativeDateTimeControl` ("Last 3/6/12 months") to
  remove the padded absolute-slider bounds (2016–2036). Better UX for review.
- **"Open" KPI:** add a count of currently-open events (`end_time` null) — needs
  a visual-scoped filter.
- **Timeline visual:** interruptions over time (by `start_time`) for trend.
- **Status filter vs per-service bar:** the status filter is single-dataset
  because the service dataset names the column `service_status`. Align naming (or
  add a cross-dataset mapping) if status should also filter the per-service bar.

### Data quality / SLA correctness
- **Health is not an authoritative SLA/outage record.** Coverage of public
  service events is incomplete and ~90-day retained. Credit candidates must be
  corroborated against the AWS Health Dashboard service-history posts. Document
  this caveat where the dashboard is consumed.
- **MULTIPLE_SERVICES parse is regex-on-free-text** and AWS wording isn't
  contractual. Add a check/monitor that flags `issue` events whose description
  yields zero parsed services ("needs manual review") rather than silently
  dropping them.
- **Global events:** the real-time rule is region-scoped; many service events
  surface via us-east-1. Ensure us-east-1 capture so going-forward `issue`
  coverage is complete.
- **Duration of open events:** `end_time` is null while ongoing, so
  `duration_hours` is null until closed. Decide how open events contribute to
  downtime metrics (e.g. compute against `now()`).

### Ingestion robustness (org scale, 500+ accounts)
- Backfill scripts have **no retry/backoff** on Health API throttling, and treat
  an API exception as end-of-data → **silent early stop / data loss**. Add
  backoff and distinguish "throttled" from "done".
- `put_events` responses are **never checked for `FailedEntryCount`** (silent
  drops under load), and entries are sent one at a time (batch up to 10).
- No handling for the **256 KB EventBridge entry limit** on very large events.
- **No DLQ** on the member→central forwarding rule; burst delivery failures are
  unrecoverable.
- Only `HealthEventBackFillOrg.py` uses the org APIs and it's **unreferenced** by
  README/OneClickSetup; the README's "org backfill" template actually uses the
  single-account API.

### Code hygiene / consistency
- Dead code: commented-out first `backfill()` in `HealthEventBackFill.py`; stray
  `print(event_data)`.
- Three overlapping backfill implementations and three tag-enrichment
  implementations — consolidate and point the README at the better ones.
- Inconsistent Lambda runtime pins (`python3.14` in `OrgHealthEventBackFill.Yaml`
  vs `python3.11` elsewhere); standardize on a supported runtime and verify it
  exists in target regions.

### Deployment / Lake Formation
- **Named-principal LF grants did not take effect** in the LF-only account; only
  `IAM_ALLOWED_PRINCIPALS` restored access (which relaxes LF governance on the
  DB). Investigate the cause (hybrid mode / grant propagation) before relying on
  named grants in a governed prod account.
- Make the LF grants **reproducible as code** (optional
  `AWS::LakeFormation::PrincipalPermissions` resources or a helper script), gated
  for LF-governed accounts, so a fresh deploy doesn't need the manual steps.

### Architecture (if HealthCompass is adopted separately)
- HEIDI (`issue` → SLA/credit) and HealthCompass (`scheduledChange` PLE → ITSM
  cleanup) operate on disjoint event categories. Keep them independent; there is
  no shared-pipeline or ticket-status join that serves the credit workflow.
