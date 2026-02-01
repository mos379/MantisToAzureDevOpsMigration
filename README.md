# Mantis to Azure DevOps Migration Tool

This repository contains scripts to migrate issues from **Mantis Bug Tracker** to **Azure DevOps** (ADO) using the ADO REST API.

It handles the end-to-end process: exporting data from a Mantis SQL dump (without needing a running Mantis instance) and importing it directly into Azure DevOps Work Items, preserving history, attachments, and metadata.

## Features

*   **Direct SQL to ADO**: Parses Mantis SQL dumps directly—no live Mantis server required.
*   **API-Based Migration**: Uses the Azure DevOps Python API for reliable Work Item creation and updates.
*   **Idempotency**: Safely re-run the script. It detects previously migrated items using tags (e.g., `Mantis-123`) to prevent duplicates.
*   **Smart Updates**: Can update existing items (Status, Fields) if you run the migration again (`--force-update`).
*   **Rich Content**:
    *   Preserves **Descriptions**, **Steps to Reproduce**, and **Additional Information**.
    *   Migrates **Comments** (Bugnotes) with original author names and timestamps.
    *   Uploads and links **Attachments** (with duplicate detection).
*   **Metadata Preservation**: Adds a "Mantis Migration Metadata" comment containing original Reporter, Date, Status, and Assignee.
*   **Safe User Assignment**: Attempts to map users by email. If the user doesn't exist in ADO, it creates the item unassigned and logs the intended owner in the metadata.
*   **State Transition Handling**: Respects ADO workflow rules (e.g., creates item as "New" first, then transitions to "Closed" or "Resolved").

## Layout

*   `source/` - Place your Mantis source code configuration and SQL dump here.
    *   `DummyProject/` - An example structure. **Replace these files with your own.**
*   `scripts/`
    *   `export_mantis_to_json.py`: Extracts data from SQL to JSON.
    *   `import_to_ado.py`: Imports JSON data to Azure DevOps.
    *   `export_mantis_attachments.py`: Extracts attachment files from SQL.
*   `export/` - Generated output directory for JSON and attachments.
*   `config.json` - Configuration for Azure DevOps connection.

## Prerequisites

1.  **Python 3.8+**
2.  **Azure DevOps Organization** and Project.
3.  **Personal Access Token (PAT)** with "Work Items (Read & Write)" scope.

## Quick Start

### 1. Setup Environment

Create a virtual environment and install dependencies:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure

Update `config.json` with your Azure DevOps details:

```json
{
  "ado_org_url": "https://dev.azure.com/YourOrg",
  "ado_project": "YourProject",
  "ado_pat": "YOUR_PERSONAL_ACCESS_TOKEN"
}
```

### 3. Prepare Your Data

We have provided a `source/DummyProject/` folder as a template. You can replace the files inside it or create a new folder for your project.

1.  Place your **Mantis SQL Dump** (e.g., `mantisbt.sql`) in `source/DummyProject/`.
2.  Copy your **Mantis Config Files** (`config_inc.php`, `config_defaults_inc.php`, `core/constant_inc.php`) to `source/DummyProject/mantisbt/`.
    *   *Note: These files are used to resolve Enum IDs (like status 10 -> "new") to readable labels.*

### 4. Export Data from Mantis

Extract the data from your Mantis SQL dump into a structured JSON file.

```bash
python3 scripts/export_mantis_to_json.py \
  --sql source/DummyProject/mantisbt.sql \
  --config-defaults source/DummyProject/mantisbt/config_defaults_inc.php \
  --config-override source/DummyProject/mantisbt/config_inc.php \
  --limit 0 \
  --output export/mantis_data.json
```

*(Optional) Export attachments to disk:*

```bash
python3 scripts/export_mantis_attachments.py \
  --sql source/DummyProject/mantisbt.sql \
  --output export/attachments
```

### 5. Import to Azure DevOps

Run the import script. This is the main migration step.

**Basic Run:**
```bash
python3 scripts/import_to_ado.py \
  --data export/mantis_data.json \
  --attachments-dir export/attachments
```

**Advanced Usage:**

*   **Filter by Project**: Only migrate bugs from a specific Mantis project name.
    ```bash
    --project-filter "My Web App"
    ```
*   **Force Update**: Update existing items (sync fields/status) if they were already migrated.
    ```bash
    --force-update
    ```
*   **Test Specific Bug**: Migrate only a single bug ID for testing.
    ```bash
    --bug-id 15
    ```

## Mapping Details

*   **Status**:
    *   `new`, `feedback`, `acknowledged` -> **New**
    *   `confirmed`, `assigned` -> **Active**
    *   `resolved`, `delivered` -> **Resolved** (or Active/Closed depending on Work Item Type)
    *   `closed` -> **Closed**
*   **Priority**: Maps Mantis priority (10-60) to ADO Priority (4-1).
*   **Work Item Type**:
    *   Severity `feature` -> **Feature**
    *   Severity `text` -> **Task**
    *   All others -> **Bug**
*   **Tags**: Adds `Mantis-<ID>`, `project-<Name>`, and `category-<Name>`.

## Troubleshooting

*   **"Unknown identity"**: If the script cannot assign a user (e.g., email mismatch), it will log a warning, leave the item **Unassigned**, and create it anyway. Check the "Mantis Migration Metadata" comment for the original owner.
*   **State Errors**: If you see errors about "State not supported", the script attempts to create items as "New" first, then updates them to the target state. Ensure your ADO process template supports the mapped states.
