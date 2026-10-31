# D2 Market digest, round 1, pass 1: Google Workspace backup (native and commercial)

Status: DRAFT FOR REVIEW. Accessed 2026-10-31. Method: 19 web search/fetch calls. Search results were relayed through a summarising fetch model, so quotations are as that model reported them. Vendor pages are marketing and are used here for feature lists only. Where a result gave no publication date, pub_date is "undated".

## Claims table

| # | Claim | Source URL | Publisher | pub_date | Accessed | Confidence | Class |
|---|---|---|---|---|---|---|---|
| 1 | Google states Vault "isn't designed to be a backup or archive tool"; its exports are for legal discovery, not efficient data processing | https://knowledge.workspace.google.com/vault/getting-started/google-vault-faq | Google | updated 2026-10-26 | 2026-10-31 | high | native |
| 2 | Vault exports cover a limited number of accounts and one service at a time, with few parallel exports, no scheduled exports, and no large-scale or high-volume backups | same as 1 | Google | updated 2026-10-26 | 2026-10-31 | high | native |
| 3 | Deleting a user removes all of their data. Admins can recover it for 20 days, after which Vault cannot search or export it | same as 1 | Google | updated 2026-10-26 | 2026-10-31 | high | native |
| 4 | Admin Drive restore works only within 25 days after the user empties trash, and only by date range ("You can't restore individual files or folders") | https://knowledge.workspace.google.com/admin/drive/recover-deleted-files-and-folders-for-drive-users | Google | updated 2026-10-26 | 2026-10-31 | high | native |
| 5 | After an admin Drive restore, "the user needs to reshare the item": sharing is not restored | same as 4 | Google | updated 2026-10-26 | 2026-10-31 | high | native |
| 6 | Drive trash auto-purges items after 30 days | same as 4 | Google | updated 2026-10-26 | 2026-10-31 | high | native |
| 7 | Admin restore of Drive and Gmail data (date range, up to 25 days back) dates from 2014; Gmail restore steps are in a separate article not retrieved here | https://workspaceupdates.googleblog.com/2014/10/restore-deleted-drive-and-gmail-data.html | Google Workspace Updates | 2014-10 | 2026-10-31 | medium (stale for current Gmail detail) | native |
| 8 | Google Cloud Backup and DR is positioned for Google Cloud and hybrid workloads; no evidence it covers Workspace | https://cloud.google.com/backup-disaster-recovery/ | Google | undated | 2026-10-31 | medium (absence of evidence) | native |
| 9 | Commvault announced Cloud Backup and Recovery for Google Workspace in Oct 2024, tied to its Google Cloud relationship | https://sourcesecurity.com/amp/news/commvault-cloud-backup-google-workspace-launched-co-12158-ga-co-1691762009-ga-co-1728458418-ga.1728460473.html | SourceSecurity (news relay) | 2024-10-09 | 2026-10-31 | medium | feature |
| 10 | A Veeam product manager said on Veeam forums that Veeam would not pursue Workspace backup for the foreseeable future. Veeam's Google offering covers Google Cloud, not Workspace | https://forums.veeam.com/viewtopic.php?p=504540 (thread set) | Veeam forums | undated | 2026-10-31 | medium | feature |
| 11 | CubeBackup is self-hosted and backs up Drive, shared drives, Gmail, Contacts, Calendar to local or private cloud/S3-compatible storage; claims point-in-time restore. Sites, Chat, Keep not mentioned | https://www.cubebackup.com/ | CubeBackup (vendor) | undated | 2026-10-31 | medium | feature |
| 12 | CubeBackup lists $5/user/year business, $2/user/year non-profit/edu, shared drives free | https://www.cubebackup.com/ | CubeBackup (vendor) | undated (freshness unconfirmed) | 2026-10-31 | low | pricing |
| 13 | Afi claims it preserves Drive document IDs, permissions, and nested Gmail labels; restores in place, to another account, or to a new folder; point-in-time; export to PST/DOCX; end-user self-service | https://afi.ai/google-workspace-backup | Afi (vendor) | undated | 2026-10-31 | medium | feature |
| 14 | Afi offers storage regions in US, EU (NL, DE), CH, UK, CA, AU, with residency routing by OU. Bring-your-own-bucket is not mentioned. Gmail backup frequency "1-24x daily" | same as 13 | Afi (vendor) | undated | 2026-10-31 | medium | feature |
| 15 | Keepit covers users, Drive (including permissions), shared drives, Gmail with labels, Calendar, Tasks. Sites are unsupported ("No public API"); Chat, Keep, Contacts are not listed, so not supported. Suspended users get only Gmail and non-native Drive files | https://web03.keepit.com/help/google-workspace-category/google-workspace-backup-coverage | Keepit (vendor help) | "as of June 2026, v10.21.0" | 2026-10-31 | high (vendor admitting gaps) | feature |
| 16 | Spanning (Kaseya/Unitrends) covers Gmail, Drive including shared drives, Calendars, Contacts, Sites; minimum 25 users; tiers for unlimited and 1-year retention | https://unitrends.com/?p=65823 | Unitrends (vendor) | undated | 2026-10-31 | medium | feature |
| 17 | Spanning claims restores to any point in time, including after account deletion, non-destructive, by admin or end user | https://spanning.com/blog/3-options-for-restoring-lost-data-in-google-apps/ | Spanning (vendor) | undated | 2026-10-31 | low-medium | feature |
| 18 | Spanning Workspace price is "Contact Us" (G2, updated 2024-11-04); 2021 third-party estimate $4 list, ~$2.6 effective per user per month | https://g2.com/products/spanning-backup/pricing ; https://afi.ai/blog/backupify-g-suite-pricing-vs-spanning-and-rest-of-competition | G2; Afi (competitor) | 2024-11-04; 2021-01 | 2026-10-31 | low (stale) | pricing |
| 19 | Backupify is now Datto SaaS Protection (Kaseya). One review says it lacks Chat, Forms, Classroom. No current public price found | https://expertinsights.com/insights/backup-and-recovery-google-workspace/ | Expert Insights (listicle) | 2026 | 2026-10-31 | low | feature |
| 20 | GYB restore failures: invalid label names; message-too-large API limit mid-restore (workaround: exclude mail over 25 MB at backup); labels flattened on mbox restore; no search filter on restore | https://groups.google.com/g/got-your-back/c/4X17MfxQSxY ; https://groups.google.com/g/got-your-back/c/3uVJ7pP-XP4 | GYB Google Group (users) | various, 2016 to 2024 | 2026-10-31 | medium | user-voice |
| 21 | Drive upload cap is about 750 GB per user per day; limits are undocumented and change. Some sources say download is about 10 TB/day | https://forum.rclone.org/t/googledrive-daily-limits-upload-750gb-download-10tb/4145 | rclone forum | undated, older | 2026-10-31 | medium | user-voice |
| 22 | Docs/Sheets/Slides over a size limit (cited as 11 MB) reportedly cannot be exported to Office formats via the API | https://docs.movebot.io/platform-guides/google/performance-and-limits | Movebot (vendor docs) | undated | 2026-10-31 | low (not confirmed vs Google docs) | feature |
| 23 | Vendors consistently frame Workspace under shared responsibility: Google runs the platform, the customer protects its own data. No primary Google page retrieved | https://www.ninjaone.com/blog/google-workspace-backup-responsibility/ | NinjaOne (vendor) | undated | 2026-10-31 | low | native |

## Capability matrix (vendor claims unless noted; "?" = not found)

| Product | Model | Gmail | Drive | Shared drives | Calendar | Contacts | Chat | Sites | Keep | Restore in place | Cross-user | Export | Storage choice | Public price |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Google native (Vault + admin restore) | built-in | retention/export only; 25-day admin restore | 25-day date-range restore, no sharing restore | yes (separate article) | no | no | Vault retention | ? | no | date range only | no | Vault export (eDiscovery) | Google | included |
| CubeBackup | self-hosted | yes | yes | yes (free) | yes | yes | ? | ? | ? | ? (claims PITR) | ? | ? | local, S3-compatible | $5/user/yr (undated) |
| Afi | SaaS | yes (nested labels) | yes (keeps IDs, permissions) | yes | yes | yes | not confirmed | not confirmed | ? | yes | yes | PST/DOCX | Afi regions incl. AU; no BYOS seen | not shown |
| Keepit | SaaS | yes (labels) | yes (permissions) | yes | yes | no | no | no (no API) | no | ? | ? | ? | Keepit cloud | ? |
| Spanning | SaaS | yes | yes | yes | yes | yes | ? | yes (claim) | ? | yes (claim) | ? | ? | vendor cloud | quote only |
| Backupify / Datto SaaS Protection | SaaS | ? | ? | ? | ? | ? | conflicting | ? | ? | ? | ? | ? | ? | quote only |
| Commvault | SaaS | announced 2024; detail not retrieved | | | | | | | | | | | | ? |
| Veeam | n/a | no Workspace product found | | | | | | | | | | | | |
| GYB (open source) | CLI | yes | no | no | no | no | no | no | no | yes, with label/size failures | yes | mbox/eml | local | free |
| rclone | CLI | no | yes (Docs export to Office) | yes | no | no | no | no | no | file copy only, no permissions | n/a | yes | any | free |

## Leads worth chasing

1. Afi's claim that it preserves Drive document IDs on restore. If true, it raises the bar a self-built restore must meet, since a new file ID breaks links. Check how it works (untrash versus recreate).
2. Keepit's "Sites: No public API". This likely applies to every vendor and suggests Sites is an industry-wide gap, not a differentiator.
3. Commvault Workspace backup (Oct 2024, Google Cloud aligned). Find out whether it runs on GCP or lets customers store backups in their own GCS.
4. CubeBackup docs: does it support GCS natively, and does it restore in place with permissions? It is the closest analogue to a self-hosted GCP build, and at about $5/user/year it sets the price anchor for build versus buy.
5. Google's Gmail admin restore article and its current window. Also check Workspace release notes for any 2025-2026 native backup feature (none found).
6. Google's official Drive API quotas page, to replace forum figures for the 750 GB/day limit and the export size limit.
7. Chat and Keep API coverage across vendors. None confirmed coverage, which suggests an API limitation (Keep API is enterprise-limited; Chat export depends on the API).

## Looked for and could not find

- Any Google-native Workspace backup product, or Google Cloud Backup and DR support for Workspace, announced 2024-2026. None found; absence of evidence only.
- A primary Google shared responsibility statement for Workspace. Only vendor paraphrases.
- Current (6 months or newer) public per-user pricing for Spanning, Backupify/Datto, Afi, SysCloud, Keepit, Acronis, Druva. SysCloud and Spanning product URLs returned 404.
- Acronis, Druva, SysCloud, and OwnBackup (OwnBackup is Salesforce-focused, now part of Salesforce; unverified belief) were not researched within budget.
- Reddit, r/sysadmin, or G2 review threads on throttling, initial seed duration, and restore fidelity. Searches returned only vendor pages. User-voice evidence here is limited to GYB and rclone forums.
- GAM-based backup limitations were not researched.
