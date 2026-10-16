# Fork notes

Changes maintained in this fork on top of upstream `aws-health-events-insight`,
plus the operational prerequisites that are not captured by the CloudFormation
templates themselves.

> Placeholders used below: `<ACCOUNT_ID>`, `<REGION>`, `<DB>` (default
> `heidi-datacollectiondb`), `<DEPLOY_ROLE_ARN>`. Substitute your own values.

## Changes in this fork

- **`src/Setup/utils/DataCollectionSetup.py`** — `get_organization_details()`
  now falls back to prompting for the Organization ID when the deploying
  identity cannot call `organizations:DescribeOrganization` (scoped roles, or
  accounts where Organizations read is denied). Previously the setup crashed.
  For a single-account deployment any value is accepted; the Organization ID
  only populates the `aws:PrincipalOrgID` condition on the central event bus,
  which governs cross-account event fan-in.

- **`src/HealthModule/HealthModuleServiceDataSetSetup.yaml`** (new) — a
  service-grain QuickSight dataset deployed as code. See
  [Service-grain dataset](#service-grain-dataset) below.

- **`src/DataCollectionModule/HeidiRoot.yaml`** — wires the new service-grain
  dataset in as a nested stack (`HealthModuleServiceDataSetSetup`), gated by the
  existing `EnableHealthModule` condition and dependent on
  `HealthModuleDataSetSetup` (which creates the `awshealthevent` Glue table).

## Lake Formation prerequisites (governed accounts)

Required only when the target account's AWS Glue Data Catalog is governed by
Lake Formation. Check with:

```
aws lakeformation get-data-lake-settings --region <REGION> \
  --query "DataLakeSettings.{CreateDBDefault:CreateDatabaseDefaultPermissions,CreateTableDefault:CreateTableDefaultPermissions}"
```

Empty arrays indicate **LF-only mode** (no IAM fallback) — explicit Lake
Formation grants are then mandatory for the deploy to succeed.

### 1. Database creation (deploy-time)

The deploying role must be able to create the Glue database. Make it a Lake
Formation **data lake administrator** (Lake Formation console → Administrative
roles and tasks → Data lake administrators), or grant catalog-level
`CREATE_DATABASE`. Without this, the `AthenaDataCollectionDB` resource fails with
`Insufficient Lake Formation permission(s): Required Create Database on Catalog`.

### 2. QuickSight read access (dataset-creation-time)

Creating the QuickSight dataset(s) runs a validation query through Athena under
the data-source role (`AthenaQuicksightAssumeRole`, assumed by QuickSight). In
LF-only mode that role, and the QuickSight service roles, need read grants on
the database and its tables, or dataset creation fails with
`Insufficient Lake Formation permission(s): Required Describe on <DB>`.

Reliable approach that is independent of the auto-generated role name — restore
IAM-based access on the database and each table (the roles already carry the
necessary IAM permissions):

```
# Database
aws lakeformation grant-permissions --region <REGION> \
  --principal DataLakePrincipalIdentifier=IAM_ALLOWED_PRINCIPALS \
  --resource '{"Database":{"CatalogId":"<ACCOUNT_ID>","Name":"<DB>"}}' \
  --permissions ALL

# Each table (wildcard is NOT allowed for IAM_ALLOWED_PRINCIPALS, so iterate)
for T in $(aws glue get-tables --region <REGION> --database-name <DB> \
            --query "TableList[].Name" --output text); do
  aws lakeformation grant-permissions --region <REGION> \
    --principal DataLakePrincipalIdentifier=IAM_ALLOWED_PRINCIPALS \
    --resource "{\"Table\":{\"CatalogId\":\"<ACCOUNT_ID>\",\"DatabaseName\":\"<DB>\",\"Name\":\"$T\"}}" \
    --permissions ALL
done
```

Granting `ALL` to `IAM_ALLOWED_PRINCIPALS` relaxes Lake Formation governance on
this database back to IAM control. That is acceptable for a sandbox/test, but in
a governed production account prefer explicit named-principal grants
(`DESCRIBE` on the database, `SELECT` on the tables) to the QuickSight Athena
role and QuickSight service roles, and keep LF enforcement on. Note: during this
session the named-principal grants were applied correctly but were not honored
for the validation query, and only the `IAM_ALLOWED_PRINCIPALS` fallback
unblocked it — investigate that behavior before relying on named grants in prod.

## Redeploy / retry behaviour

The setup deploys with `--disable-rollback`. A failed create leaves the stack in
`CREATE_FAILED` (not `ROLLBACK_COMPLETE`), which can be **retried in place** —
re-run the deploy and CloudFormation resumes from the failed resource, keeping
already-created resources. Do **not** delete the stack to retry; deleting
destroys the database/tables/role and forces the Lake Formation grants to be
redone.

## Service-grain dataset

`HealthModuleServiceDataSetSetup.yaml` creates a second QuickSight dataset at
**(event, service) grain**, alongside the existing event-grain dataset. It:

- Deduplicates to the latest row per event (`rank() ... = 1`), matching the
  event-grain dataset.
- For `service = 'MULTIPLE_SERVICES'` events, parses the event description and
  emits one row per service, with `service_status` of `affected` (services
  listed as `(Disrupted)`) or `recovered` (listed under "now operating
  normally").
- Passes single-service events through with `service_status = 'single'`.

Use the event-grain dataset for event counts and durations; use this dataset for
per-service rollups. Do not merge the two grains in one analysis or event-level
metrics will double-count.

**Caveat:** the service list is extracted from free-text with two regexes
(`affected by this event: ...` and `now operating normally: ...`). AWS wording is
consistent for region-wide operational events but is not a contract. Treat an
event whose `MULTIPLE_SERVICES` description yields no parsed services as "needs
manual review," and corroborate anything used for SLA/credit claims against the
authoritative AWS Health Dashboard service-history post for that event.

## Issue-focused SLA build

Scopes the analytical and action layers to service-interruption events
(`eventTypeCategory = 'issue'`) for SLA / service-credit evaluation, while
ingestion and the S3 lake remain broad (all categories kept). "Broad lake,
narrow SPICE and dashboard."

- **`src/HealthModule/HealthModuleIssueDataSetSetup.yaml`** (new) — event-grain,
  issue-only QuickSight dataset. Deduped to latest row per event; emits service,
  region, scope (PUBLIC / account-specific), start/end, normalized status, and
  computed `duration_hours`.
- **`src/HealthModule/HealthModuleServiceDataSetSetup.yaml`** (changed) — now
  scoped to `issue` (added `WHERE detail.eventtypecategory = 'issue'` in the
  `latest` CTE). Still explodes `MULTIPLE_SERVICES` operational issues into one
  row per affected service; single-service issue events pass through.
- **`src/CreditModule/CreditTicketModule.yaml`** (new) — EventBridge rule on the
  central bus filtered to `issue` → idempotent Lambda → Jira "evaluate for SLA
  service credit" ticket. One ticket per `eventArn` (DynamoDB idempotency table);
  later updates comment instead of duplicating. Jira creds in Secrets Manager,
  DLQ on the rule target and Lambda, reserved concurrency = 2, 429 retry/backoff.
- **`src/DataCollectionModule/HeidiRoot.yaml`** (changed) — wires the issue
  dataset (under `EnableHealthModule`) and the credit module (opt-in via new
  `EnableCreditModule` parameter, default `no`, with `JiraBaseUrl`,
  `JiraProjectKey`, `JiraSecretArn`).

### Deploying the credit module

Opt-in; default deploys are unaffected. Create the Jira secret, then enable:

```
aws secretsmanager create-secret --name heidi-jira --region <REGION> \
  --secret-string '{"email":"<jira-user-email>","apiToken":"<token>"}'
```

Add to the SAM deploy parameter overrides:
`EnableCreditModule=yes JiraBaseUrl=https://<org>.atlassian.net JiraProjectKey=<KEY> JiraSecretArn=<secret-arn>`

The rule matches `aws.health`, `heidi.health`, and `awshealthtest` sources with
`detail.eventTypeCategory = issue`, so backfilled and real-time interruptions
both create tickets. Scope further to region-wide events by adding
`eventScopeCode: ["PUBLIC"]` to the rule's `EventPattern`.
