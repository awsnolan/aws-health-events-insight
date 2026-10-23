## **Health Events Intelligence Dashboards and Insights (HEIDI)**
Single pane of glass for all your Health events across different accounts, regions and organizations.

 ![Alt Text](https://github.com/awsnolan/aws-health-events-insight/blob/main/img/dashboard.gif)

> **Note:** the dashboard GIF and architecture image below reflect the optional
> **QuickSight** output path. This fork defaults to an **S3 extract** output
> (`OutputMode=s3`) that produces CSV/JSON files and deploys no QuickSight
> resources. See [Output Modes](#output-modes).

## **Table of Contents**
- [What's New?](#whats-new)
- [Solution Architecture](#solution-architecture)
- [Modules](#modules)
- [Output Modes](#output-modes)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
    - [Data Collection Account Setup](#data-collection-setup)
    - [Member Setup](#member-setup--not-required-for-heidi-in-delegated-health-admin-account-)
- [Cost Allocation Tags](#cost-allocation-tags)
- [Update Metadata](#update-metadata-optional)
- [Backfill HealthEvents](#backfill-healthevents-optional)
- [Setup Validation](#setup-validation)
- [SLA / Issue-Event Use Case](#sla--issue-event-use-case)
- [Troubleshooting](#troubleshooting)

## **Whats New?**
*NEW:* Heidi now presents an efficient mechanism for data collection, visualization, and notifications. Operating on an event-driven model, Heidi simplifies the collection of data from various AWS services across numerous accounts within multiple AWS organizations. Heidi can surface the collected events either as scheduled **S3 CSV/JSON extracts** (the default, no QuickSight required) or as **QuickSight dashboards**, enabling customers to conveniently access a comprehensive overview without the need to log in to each individual AWS account.

Heidi consists of the following modules:

* **Health Module** — unified view of upcoming events, planned events (EOL), scheduled events and issues across all AWS accounts and AWS Organizations.
* **Output Module** — scheduled Athena extract of the issue (event-grain) and service-grain data to S3 as CSV or JSON. Deployed when `OutputMode` is `s3` or `both`.
* **Notification Module** — powered by AWS Chatbot to get notifications on Slack or Teams.
* **Credit/Ticketing Module** *(opt-in)* — opens Jira tickets to evaluate service-interruption (`issue`) events for SLA service credits. Off by default (`EnableCreditModule=no`).

This fork is oriented toward triaging service-interruption (`issue`) events for SLA review. The issue/SLA datasets, the service-grain `MULTIPLE_SERVICES` explosion, the credit module, and the Lake Formation prerequisites are documented in detail in [docs/FORK-NOTES.md](docs/FORK-NOTES.md).

## **Solution Architecture**

HEIDI Data Collection Framework enables you to collect data from different accounts, regions and organizations. The following diagram illustrates a multi-account structure. The DataCollection Account refers to the account which receives events routed from the current account as well as all other accounts within your AWS Organizations, and which produces the unified output (S3 extract and/or QuickSight dashboard). The link accounts refer to any accounts other than the DataCollection Account, routing enriched events to the DataCollection Account. The DataCollection architecture consists of an AWS EventBridge custom bus, an AWS EventBridge rule, Amazon Kinesis Data Firehose and an Amazon S3 bucket. The query engine is Amazon Athena; the presentation/output layer is either a scheduled S3 extract (default) or an Amazon QuickSight dashboard (optional).

1. AWS services generate events, which are sent to the default event bus in member/linked accounts.
2. A corresponding EventBridge rule on the default event bus directs events to a centralized bus upon pattern matching.
3. The centralized event bus then routes the events to Kinesis.
4. Kinesis Data Firehose processes and stores the events in S3 buckets.
5. Athena queries the S3 buckets via the `awshealthevent` Glue table.
6. **Output:** by default a scheduled Lambda writes CSV/JSON extracts to S3 (`OutputMode=s3`). Optionally, QuickSight provides interactive dashboards (`OutputMode=quicksight` or `both`).

 ![ArchitectureDiag](img/Heidibaseline.jpg)

> The diagram above depicts the QuickSight output path. In the default S3 mode,
> steps 1–5 are identical and step 6 is the scheduled S3 extract instead of
> QuickSight.

## **Modules**

| Module | Template | When deployed |
|---|---|---|
| Health (data collection + Glue tables) | `DataCollectionModule.yaml`, `HealthModuleCollectionSetup.yaml` | `EnableHealthModule=yes` |
| Output (S3 extract) | `OutputModule/S3ExtractModule.yaml` | `OutputMode` = `s3` or `both` |
| QuickSight datasets + SLA/issue analysis | `HealthModule/HealthModule*DataSetSetup.yaml`, `HealthModule*QSAnalysis.yaml` | `OutputMode` = `quicksight` or `both` |
| Notification | `NotificationModule/NotificationModule.yaml` | `EnableNotificationModule=yes` |
| Credit/Ticketing (Jira, opt-in) | `CreditModule/CreditTicketModule.yaml` | `EnableCreditModule=yes` |

## **Output Modes**

HEIDI's output is controlled by the `OutputMode` parameter (`HeidiRoot.yaml`):

| `OutputMode` | What deploys | Notes |
|---|---|---|
| `s3` *(default)* | Scheduled S3 extract only. **No** QuickSight datasource, datasets, analyses, or the QuickSight-only IAM role. | Lean footprint. `QuickSightAnalysisAuthor` is not required. |
| `quicksight` | QuickSight datasets and the SLA/issue analyses. | Requires the QuickSight prerequisites below. |
| `both` | S3 extract **and** QuickSight. | |

Related parameters (apply when `OutputMode` is `s3` or `both`):
- `ExtractFormat` — `CSV` (default) or `JSON`.
- `ExtractSchedule` — EventBridge schedule expression (default `rate(1 day)`).

**S3 extract output layout:**

```
s3://<DataCollectionBucket>/heidi-extracts/issue/latest/issue.csv
s3://<DataCollectionBucket>/heidi-extracts/issue/run=<timestamp>/issue.csv
s3://<DataCollectionBucket>/heidi-extracts/service/latest/service.csv
s3://<DataCollectionBucket>/heidi-extracts/service/run=<timestamp>/service.csv
```

`latest/` always holds the most recent run; each `run=<timestamp>/` is retained for history/comparison.

### Service-usage filtering (optional)

Set `ServiceUsageMode` to limit the extract to services your business actually uses:

| `ServiceUsageMode` | Behaviour |
|---|---|
| `off` *(default)* | All events; no usage column. |
| `flag` | Adds a `service_in_use` column (`Y`/`N`/`UNREVIEWED`); nothing dropped. |
| `filter` | As `flag`, plus drops PUBLIC events for services you explicitly marked not-in-use. Account-specific events always kept. |

In `flag`/`filter` mode the Lambda maintains a `services_in_use.csv` reference (under `DataCollection-metadata/ReferenceOds/ServicesInUse/`, sample in the repo) that enumerates the services actually seen in your data — you just edit the `in_use` column (`Y`/`N`). Services it hasn't seen classified before are kept, flagged `UNREVIEWED`, and reported each run under `heidi-extracts/service-review/`, so new AWS services that ship never get silently hidden. Matching is normalized and alias-mapped so Health's service codes and the long names in `MULTIPLE_SERVICES` events line up. Full detail in [docs/FORK-NOTES.md](docs/FORK-NOTES.md).

## **Prerequisites**

1. To backfill your existing health events, the solution uses the AWS Health API. You need a **Business Support or Enterprise Support** plan from AWS Support to use this API. (Basic and Developer Support do not include Health API access.)

**QuickSight prerequisites — only required if `OutputMode` is `quicksight` or `both`** (skip entirely for the default `s3` mode):

2. Sign up for QuickSight if you have never used it in the Data Collection account. To use the forecast capability in QuickSight, sign up for the Enterprise Edition.
3. Verify QuickSight service has access to Amazon Athena. To enable, go to security and permissions under *manage QuickSight*.
4. The AWS Health Event Dashboard uses [SPICE](https://docs.aws.amazon.com/quicksight/latest/user/spice.html) to hold data. Go to SPICE capacity under manage QuickSight and verify you have the required space.

## **Installation**

In this section, we will guide you through configuring HEIDI for AWS Health Events in both the Data Collection and Member accounts. Our recommendation is to deploy HEIDI in a delegated health admin account so that it can automatically receive feeds from all other accounts within your organization without any additional setup. You can designate up to 5 linked accounts as delegated health admin accounts within your AWS organization. To register an account as a delegated health admin, please follow these  [instructions](https://docs.aws.amazon.com/health/latest/ug/delegated-administrator-organizational-view.html#register-a-delegated-administrator)

### **Data Collection Setup**

The setup script provided in this repo will set up all the necessary components required to receive AWS health events from other accounts and other regions. This can be your payer/organization or any other linked/member AWS account which you designate to receive AWS Health data from other HEIDI Member accounts and regions. 

1. To start, log in to your AWS console and launch **AWS CloudShell** and clone the aws-health-events-insight repo. You can use your local environment provided that you have assumed a role with necessary permissions to deploy the solution.

        git clone https://github.com/awsnolan/aws-health-events-insight.git

2. Go to the `aws-health-events-insight` directory and run `OneClickSetup.py` and provide account specific inputs. The setup script generates a CloudFormation stack that deploys all necessary AWS resources. You will be asked to choose an `OutputMode` (default `s3`); choose `quicksight` or `both` to also deploy the QuickSight dashboard.

        cd aws-health-events-insight/src/Setup
        python3 OneClickSetup.py

3. Once CloudFormation status changes to **CREATE_COMPLETE** (about 10-15 minutes), verify the deployment:
   - **S3 mode:** trigger the extract Lambda once (or wait for the schedule) and confirm objects under `s3://<DataCollectionBucket>/heidi-extracts/`.
   - **QuickSight mode:** go to QuickSight Analysis and verify the initial deployment.

### **Member Setup ( Not required for Heidi in delegated health admin account )**

You can now receive a feed of AWS Health events on Amazon EventBridge from all accounts within your organization in AWS Organizations using organizational view and delegated administrator. With this feature, if you are deploying HEIDI in the health delegated administrator account, it will ingest AWS Health events from all other accounts and you dont have to run this setup.

**Note:** If HEIDI is deployed in the health delegated admin account, you dont have to run member setup in any other linked accounts across the organization. This step can be skipped. However, if HEIDI is not deployed in the health delegated admin account, or if the account is outside your AWS organization, you must complete this setup to enable those accounts to send data feeds to the HEIDI data collection account.

If you have additional Payer/Organization IDs, you are also required to run member setup within the delegated health admin account for each additional Payer. 

#### (Option 1) One Click Setup Script to add Member Region
1. Setup AWS credentials for DataCollection Account. Or, log in to your AWS console and launch **AWS CloudShell**.
2. Go to `aws-health-events-insight` directory and run `OneClickSetup.py` and select `Member Setup` provide necessary inputs. 

        cd aws-health-events-insight/src/Setup
        python3 OneClickSetup.py

#### (Option 2) Bulk deployment via CloudFormation StackSet
1. In CloudFormation console, create a StackSet with new resources from the template file [HealthModuleCollectionSetup.yaml](https://github.com/awsnolan/aws-health-events-insight/blob/main/src/HealthModule/HealthModuleCollectionSetup.yaml).
2. Input variables
3. Select deployment targets (Deploy to OU or deploy to organization).
4. Select regions to deploy.
5. Submit.

**Note:** If you are NOT deploying HEIDI in the health delegated admin account, you MUST complete Member Setup for each Link Account and Region for which you want to receive events. To receive global events, you must create Member account/region setup for the US East (N. Virginia) region and US West (Oregon) Region as the backup region if needed.

## **Cost Allocation Tags**

All resources created by this fork are tagged `Application=HEIDI` (the default stack tag). To see HEIDI's cost broken out in Cost Explorer or your CUR:

1. In the Billing console, go to **Cost allocation tags** and activate the `Application` user-defined tag (if not already active).
2. Attribution is **not retroactive** — cost data accrues from tag activation/application forward and appears in Cost Explorer/CUR after roughly 24 hours.

**Caveat (Athena):** HEIDI's Athena queries run in the shared default `primary` workgroup, so Athena spend is not cleanly attributable by tag without a dedicated workgroup. The remaining consumption (Firehose, Lambda, S3, EventBridge) is negligible, so HEIDI's real operating cost in the default S3 mode is a few cents or less — there are no always-on, hourly-billed resources.

## **Update Metadata (optional)**
This is an optional step, primarily useful for the QuickSight output. You can map AWS AccountIDs with Account Name and Account Tags (AppID, Env, etc.) which the QuickSight dataset joins on.

1. From your Payer/Organization account, go to AWS Organizations and export the account list. If you don't have access or can't get the export list, you can create one from [this sample file](https://github.com/awsnolan/aws-health-events-insight/blob/main/src/ReferenceOds/AccountsInfo/Organization_accounts_information_sample.csv).

   ![Export Account List](img/exportAccountList.jpg)

2. For Account Tag, edit the account list CSV file and add the Tag field as shown below.

   ![Account Tag](img/AccountTag.jpg)

3. **Important:** Upload the file to a specific Amazon S3 location so that the QuickSight dataset can join the data and create the mapping. 

   ![S3 Location](img/s3Location.jpg)

## **Backfill HealthEvents (optional)**

**Option 1: Manual backfill for individual Account** 

By default, Heidi does not automatically backfill older health events. However, you can manually perform this task using the [HealthEventBackFill.py](https://github.com/awsnolan/aws-health-events-insight/blob/main/src/Setup/utils/HealthEventBackFill.py) script. You need to run this Python script in each account where backfill is required.

Go to `aws-health-events-insight` directory and run `HealthEventBackFill.py` and provide necessary inputs. 

        cd aws-health-events-insight/src/Setup/utils
        python3 HealthEventBackFill.py

Ensure to execute this script in the specific AWS account for which you intend to backfill the events. 

**Option 2: Bulk Backfill across AWS Organization/Organizational Unit (OU)**

1. In CloudFormation console, create a StackSet with new resources from the template file [OrgHealthEventBackfill.yaml](https://github.com/awsnolan/aws-health-events-insight/blob/main/src/HealthModule/OrgHealthEventBackFill.Yaml). 
2. Input Centerlized Heidi DataCollection Account, DataCollection Region and ResourcePrefix. 
3. Select deployment targets (Deploy to OU or deploy to organization).
4. Select us-east-1 region to deploy.
5. Submit.

Once stacksets are deployed, It will create lambda function which will send events from individual accounts to Heidi datacollection account. You can go ahead and remove stacksets once they are deployed as this is once time activity to backfill the events.

## **Setup Validation**
Send a mock event to test setup.

1. Go to EventBridge console and choose default event bus. (You can choose any member account or region) and click the **Send events** button.
2. **Important** Put the **Event source** and **Detail type** as `heidi.health` , otherwise the rule will discard the mock event.
3. Copy the content below `Send a mock event to test Control Account setup` from [MockEvent.json](https://github.com/awsnolan/aws-health-events-insight/blob/main/src/HealthModule/MockHealthEvent.json) and paste it in the **Event detail** field.
4. Click **Send**.

You will see the event land in Amazon S3 under `DataCollection-data/`. To see it in the output:
- **S3 mode:** invoke the extract Lambda and check `heidi-extracts/`.
- **QuickSight mode:** refresh the QuickSight dataset manually.

## **SLA / Issue-Event Use Case**

This fork is purpose-built to help triage AWS service-interruption (`issue`) events for SLA service-credit decisions. Ingestion stays broad (all event categories land in the S3 lake), while the issue/SLA datasets, dashboard, and the optional credit-ticketing module are scoped to `eventTypeCategory = 'issue'`. The full design — the event-grain and service-grain (`MULTIPLE_SERVICES` explosion) datasets, neutral-vocabulary labelling, the Jira credit module, and the Lake Formation prerequisites — is documented in [docs/FORK-NOTES.md](docs/FORK-NOTES.md).

> HEIDI records the AWS-side service event; it is not an availability/SLA
> measurement tool. Corroborate anything used for a credit claim against the
> authoritative AWS Health Dashboard service-history post for that event.

## **FAQ**

**Q: Does HEIDI support multiple payer/AWS organizations?**\
**A:** Yes, HEIDI allows you to include additional organizational IDs during deployment.

**Q: Is member setup required in all linked accounts?**\
**A:** No, if the data collection deployment is in the delegated health admin account, member setup is NOT required in all linked accounts. See Member Setup for more details.

**Q: What is the cost of the Heidi solution?**\
**A:** In the default `s3` output mode there are no always-on resources; cost is consumption-only (Athena, Firehose, Lambda, S3, EventBridge) and is typically a few cents — effectively negligible for a single account. The `quicksight` mode adds Amazon QuickSight SPICE and author/reader licensing, which is the dominant cost when enabled. See [Cost Allocation Tags](#cost-allocation-tags) to attribute HEIDI's spend precisely.

## **Troubleshooting**

#### ***1. SYNTAX_ERROR: line 41:15: UNNEST on other than the right side of CROSS JOIN is not supported***

This implies that you are using Athena V2. Please upgrade worker to Athena V3. Athena V2 is on deprecated path.

#### ***2. Template format error: Unrecognized resource types: [AWS::QuickSight::RefreshSchedule]***

`AWS::QuickSight::RefreshSchedule` does not exist in certain regions such as us-west-1, ca-central-1 etc. You can comment out the `QSDataSetHealthEventRefresh` section in [HealthModuleDataSetSetup.yaml](https://github.com/awsnolan/aws-health-events-insight/blob/main/src/HealthModule/HealthModuleDataSetSetup.yaml) and set up the refresh schedule from the QuickSight console. (Applies to `quicksight`/`both` modes only.)

#### ***3. Insufficient Lake Formation permission(s) / Athena reports TABLE_NOT_FOUND***

If the account's Glue Data Catalog is governed by Lake Formation, deploys and queries need explicit LF grants. Deploy with **`LakeFormationGoverned=yes`** to create these grants automatically (`AWS::LakeFormation::PrincipalPermissions` on the database and each table, granting `IAM_ALLOWED_PRINCIPALS`). The deploying principal must still be a Lake Formation data-lake admin to create the database. In LF-only accounts, the reliable fix observed in this fork was granting `IAM_ALLOWED_PRINCIPALS` on the database **and each table** (named/SAML grants did not take effect). 

Note for S3 mode: because the `awshealthevent` table is recreated if it is ever dropped (e.g. switching output modes), a recreated table **loses its LF grant**, and Athena then reports `TABLE_NOT_FOUND` even though the table exists in Glue. Re-apply the grant after any redeploy that recreates the table. Full commands and the recommended production approach are in the Lake Formation section of [docs/FORK-NOTES.md](docs/FORK-NOTES.md).

#### ***4. Possible Reasons for No Data in Output:***

1. Your AWS environment is relatively new and does not currently have any AWS Health Events. To verify this, please check the AWS Health Dashboard on the AWS Console and send a mock event.
2. (QuickSight) The DataSet was created before the event could be backfilled by Kinesis Data Firehose. To resolve this, manually refresh the QuickSight DataSet.
3. (S3) The scheduled extract has not run yet. Invoke the extract Lambda manually to produce output immediately.

#### ***5. Not getting Notifications on Slack/Team:***

1. Go to EventBridge and see if it has failures sending events to SNS. It's possible that SNS is encrypted with KMS keys which is not accessible by EventBridge service role. 
2. Your Amazon SNS topic must use an AWS KMS key that is customer managed. Visit [SNS-EB-Notification](https://repost.aws/knowledge-center/sns-not-getting-eventbridge-notification) to learn more. 


[![GitHub Clones](https://img.shields.io/badge/dynamic/json?color=success&label=Clone&query=count&url=https://gist.githubusercontent.com/bajwkanw/24109c8c210fc89367f044d83d07c1bc/raw/clone.json&logo=github)](https://github.com/awsnolan/aws-health-events-insight)
