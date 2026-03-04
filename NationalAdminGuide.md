# F3 National Administrator Guide

This toolkit is designed to empower F3 Regional Administrators to clean and format their historical backblast data for migration into the National Database. As a National Admin, your role is to support this process by providing secure access to global data and validating final exports.

## 1. Data Security & Coordination

The transformation pipeline relies on `import/user_master.csv`, which contains global F3 user IDs, names, and emails.

> [!CAUTION]
> **PII Protection**: `user_master.csv` contains sensitive personal information.
> - **DO NOT** commit this file to public repositories.
> - **DO NOT** share this file with unauthorized local users.
> - **National Admins** should either run the `fetch_master_users.py` script for the region or provide a secure, one-time export for their migration window.

### Supporting Regional Admins
Regions will often need your help with:
1.  **Home Region IDs**: Providing the official `REGION_ID` for their `config.py`.
2.  **Org/Location IDs**: Helping them map their local AOs to the official IDs in the National Database (usually found in `locations.csv`).

## 2. Validation Workflow

Before importing regional data into the production database, perform the following quality checks:

### User Matching Audit
Check the `{REGION_NAME}_missing_users.csv` output.
- If this list is long, the region may have missed alias mappings.
- Encourage them to update `import/aliases.json` to reduce unmatched users.

### Comma-Free Compliance
The scripts automatically strip commas from IDs to ensure strict integer alignment. Verify that `user_id`, `org_id`, and `location_id` columns contains only raw numbers.

## 3. Modular Deployment
This tool is built to be "bring-your-own-data". 
- **WordPress Only**: If a region only has WP, they only need `convert.py`.
- **Google Sheets Only**: If they use Sheets, they need `extract_missing_qs.py`.

Encourage regions to only use the modules relevant to their history to keep the migration clean.
