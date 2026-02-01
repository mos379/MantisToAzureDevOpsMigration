#!/usr/bin/env python3
import argparse
import json
import os
import sys
import datetime

try:
    from azure.devops.connection import Connection
    from msrest.authentication import BasicAuthentication
    # Try importing from v7_1, fallback to v7_0 or v6_0
    try:
        from azure.devops.v7_1.work_item_tracking.models import JsonPatchOperation, Wiql
    except ImportError:
        try:
            from azure.devops.v7_0.work_item_tracking.models import JsonPatchOperation, Wiql
        except ImportError:
            from azure.devops.v6_0.work_item_tracking.models import JsonPatchOperation, Wiql
except ImportError:
    print("Error: azure-devops library not found.")
    print("Please install it using: pip install -r requirements.txt")
    sys.exit(1)

# --- Field Mappings ---

STATUS_MAP = {

    10: "New", 20: "New", 25: "New",

    30: "Active", 40: "Active", 50: "Active",

    80: "Resolved", 85: "Resolved",

    90: "Closed"  # Reverted back to Closed

}





PRIORITY_MAP = {

    10: 4, 20: 4,  # Low

    30: 3,         # Normal

    40: 2,         # High

    50: 1, 60: 1   # Urgent/Immediate

}



SEVERITY_TYPE_MAP = {

    10: "Feature", 30: "Task", 40: "Feature",

    50: "Bug", 60: "Bug", 70: "Bug", 80: "Bug"

}



def format_timestamp(ts):

    if not ts:

        return "Unknown Date"

    return datetime.datetime.fromtimestamp(int(ts), datetime.timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')



def format_user(user_obj):

    if not user_obj or not user_obj.get('username'):

        return "Unknown User"

    name = user_obj.get('realname') or user_obj.get('username')

    return f"{name} ({user_obj.get('username')})"



def get_work_item_by_mantis_id(wit_client, project, mantis_id):

    """Finds an existing Work Item by the 'Mantis-{mantis_id}' tag."""

    query = f"""

        SELECT [System.Id]

        FROM WorkItems

        WHERE [System.TeamProject] = '{project}'

        AND [System.Tags] CONTAINS 'Mantis-{mantis_id}'

    """

    wiql = Wiql(query=query)

    result = wit_client.query_by_wiql(wiql)

    

    if result.work_items:

        return result.work_items[0].id

    return None



def main():
    parser = argparse.ArgumentParser(description="Import/Update Work Items from Mantis JSON to Azure DevOps")
    parser.add_argument("--config", default="config.json", help="Path to config.json")
    parser.add_argument("--data", required=True, help="Path to mantis_data.json export")
    parser.add_argument("--attachments-dir", help="Directory containing exported attachments (e.g. export/attachments)")
    parser.add_argument("--bug-id", help="Only process a specific Mantis Bug ID")
    parser.add_argument("--project-filter", help="Only process bugs from a specific Mantis Project Name")
    parser.add_argument("--force-update", action="store_true", help="Update fields even if Work Item exists")
    args = parser.parse_args()

    # Locate config file
    config_path = os.path.abspath(args.config)
    if not os.path.exists(config_path):
        root_config = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.json")
        if os.path.exists(root_config):
            config_path = root_config
        else:
            print(f"Error: Config file not found at {config_path}")
            sys.exit(1)

    with open(config_path, "r") as f:
        config = json.load(f)

    org_url = config.get("ado_org_url")
    project = config.get("ado_project")
    pat = config.get("ado_pat")

    if not org_url or not pat or pat == "REPLACE_WITH_PAT":
        print("Error: Invalid configuration in config.json.")
        sys.exit(1)

    # Load Mantis Data
    if not os.path.exists(args.data):
        print(f"Error: Data file not found at {args.data}")
        sys.exit(1)
        
    print(f"Loading data from {args.data}...")
    with open(args.data, "r") as f:
        mantis_data = json.load(f)

    bugs = mantis_data.get("bugs_by_id", {})
    print(f"Found {len(bugs)} bugs to process.")

    print(f"Connecting to {org_url} (Project: {project})...")
    credentials = BasicAuthentication('', pat)
    connection = Connection(base_url=org_url, creds=credentials)
    wit_client = connection.clients.get_work_item_tracking_client()

    for bug_id, bug in bugs.items():
        if args.bug_id and str(bug_id) != str(args.bug_id):
            continue
            
        project_name = bug.get('project', {}).get('name', 'Unknown')
        if args.project_filter and args.project_filter.lower() != project_name.lower():
            continue

        summary = bug.get('summary')
        print(f"Processing Mantis ID {bug_id} [{project_name}]: {summary}")

        # Check if exists
        existing_id = get_work_item_by_mantis_id(wit_client, project, bug_id)
        
        # Map Fields
        status_code = int(bug.get('status') or 10)
        severity_code = int(bug.get('severity') or 50)
        priority_code = int(bug.get('priority') or 30)
        
        target_state = STATUS_MAP.get(status_code, "New")
        target_priority = PRIORITY_MAP.get(priority_code, 3)
        work_item_type = SEVERITY_TYPE_MAP.get(severity_code, "Bug")
        
        # User Mapping (Assigned To)
        handler = bug.get('handler', {})
        assigned_to = handler.get('email') or handler.get('username') or ""
        
        # Build Tags
        tags_list = [f"Mantis-{bug_id}"]
        if bug.get('project', {}).get('name'):
            tags_list.append(f"project-{bug['project']['name']}")
        if bug.get('category', {}).get('name'):
            tags_list.append(bug['category']['name'])
        
        tags_str = "; ".join(tags_list)

        # Prepare Description and Repro Steps
        description_text = (bug.get('description') or "").strip()
        steps_text = (bug.get('steps_to_reproduce') or "").strip()
        additional_text = (bug.get('additional_information') or "").strip()
        
        repro_steps_val = None
        final_description = description_text.replace("\n", "<br>")

        if work_item_type == "Bug":
            if steps_text:
                repro_steps_val = steps_text.replace("\n", "<br>")
            
            if additional_text:
                final_description += "<br><br><strong>Additional Information:</strong><br>" + additional_text.replace("\n", "<br>")
        else:
            # Combine all for non-bugs
            if steps_text:
                final_description += "<br><br><strong>Steps to Reproduce:</strong><br>" + steps_text.replace("\n", "<br>")
            if additional_text:
                final_description += "<br><br><strong>Additional Information:</strong><br>" + additional_text.replace("\n", "<br>")

        if existing_id:
            print(f"  -> Found existing Work Item ID: {existing_id}")
            if not args.force_update:
                print("  -> Skipping update (use --force-update to override).")
                continue
            
            print("  -> Updating existing Work Item fields...")
            patch_document = [
                JsonPatchOperation(op="add", path="/fields/System.Title", value=summary),
                JsonPatchOperation(op="add", path="/fields/System.Description", value=final_description),
                JsonPatchOperation(op="add", path="/fields/Microsoft.VSTS.Common.Priority", value=target_priority),
                JsonPatchOperation(op="add", path="/fields/System.Tags", value=tags_str)
            ]
            if repro_steps_val:
                 patch_document.append(JsonPatchOperation(op="add", path="/fields/Microsoft.VSTS.TCM.ReproSteps", value=repro_steps_val))
            
            # Try to assign, but don't fail update if user unknown
            if assigned_to:
                patch_document.append(JsonPatchOperation(op="add", path="/fields/System.AssignedTo", value=assigned_to))

            try:
                wi = wit_client.update_work_item(document=patch_document, id=existing_id)
            except Exception as update_err:
                if "unknown identity" in str(update_err):
                    print(f"  -> Warning: User '{assigned_to}' unknown. Removing assignment and retrying...")
                    # Remove the assignment operation (last one) and retry
                    patch_document.pop() 
                    wi = wit_client.update_work_item(document=patch_document, id=existing_id)
                else:
                    raise update_err
            
            # Update State separately
            if target_state != wi.fields.get('System.State'):
                print(f"  -> Updating State to: {target_state}")
                try:
                    state_patch = [JsonPatchOperation(op="add", path="/fields/System.State", value=target_state)]
                    wi = wit_client.update_work_item(document=state_patch, id=wi.id)
                except Exception as state_err:
                    print(f"  -> Warning: Failed to set State to '{target_state}': {state_err}")
            
            print(f"  -> Updated Work Item ID: {wi.id}")

        else:
            print(f"  -> Creating new '{work_item_type}'...")
            # Step 1: Create as New
            patch_document = [
                JsonPatchOperation(op="add", path="/fields/System.Title", value=summary),
                JsonPatchOperation(op="add", path="/fields/System.Description", value=final_description),
                JsonPatchOperation(op="add", path="/fields/System.State", value="New"),
                JsonPatchOperation(op="add", path="/fields/Microsoft.VSTS.Common.Priority", value=target_priority),
                JsonPatchOperation(op="add", path="/fields/System.Tags", value=tags_str)
            ]
            if repro_steps_val:
                 patch_document.append(JsonPatchOperation(op="add", path="/fields/Microsoft.VSTS.TCM.ReproSteps", value=repro_steps_val))

            if assigned_to:
                patch_document.append(JsonPatchOperation(op="add", path="/fields/System.AssignedTo", value=assigned_to))

            try:
                wi = wit_client.create_work_item(document=patch_document, project=project, type=work_item_type)
                print(f"  -> Created ADO Work Item ID: {wi.id}")
                
                # Add Metadata Comment
                original_date = format_timestamp(bug.get('date_submitted'))
                reporter = format_user(bug.get('reporter'))
                handler_name = format_user(bug.get('handler'))
                
                meta_comment = (
                    f"<strong>[Mantis Migration Metadata]</strong><br>"
                    f"<strong>Mantis ID:</strong> {bug.get('id')}<br>"
                    f"<strong>Original Reporter:</strong> {reporter}<br>"
                    f"<strong>Original Date:</strong> {original_date}<br>"
                    f"<strong>Original Assigned To:</strong> {handler_name}<br>"
                    f"<strong>Original Status:</strong> {bug.get('status_label')} ({target_state})<br>"
                    f"<strong>Original Priority:</strong> {bug.get('priority_label')}<br>"
                    f"<strong>Original Severity:</strong> {bug.get('severity_label')}<br>"
                )
                
                meta_patch = [
                    JsonPatchOperation(op="add", path="/fields/System.History", value=meta_comment)
                ]
                wit_client.update_work_item(document=meta_patch, id=wi.id)

                # Step 2: Update to Target State if different
                if target_state != "New":
                    state_patch = [
                        JsonPatchOperation(op="add", path="/fields/System.State", value=target_state)
                    ]
                    try:
                        wi = wit_client.update_work_item(document=state_patch, id=wi.id)
                        print(f"  -> Updated State to: {target_state}")
                    except Exception as state_err:
                        print(f"  -> Warning: Failed to set State to '{target_state}': {state_err}")

            except Exception as e:
                if "unknown identity" in str(e) and assigned_to:
                     print(f"  -> Warning: User '{assigned_to}' unknown. Retrying creation without assignment...")
                     patch_document.pop() # Remove assignment
                     # Retry creation
                     try:
                        wi = wit_client.create_work_item(document=patch_document, project=project, type=work_item_type)
                        print(f"  -> Created ADO Work Item ID: {wi.id} (Unassigned)")
                        
                        # Add Metadata Comment (Duplicate code, but necessary for retry path)
                        original_date = format_timestamp(bug.get('date_submitted'))
                        reporter = format_user(bug.get('reporter'))
                        handler_name = format_user(bug.get('handler'))
                        
                        meta_comment = (
                            f"<strong>[Mantis Migration Metadata]</strong><br>"
                            f"<strong>Mantis ID:</strong> {bug.get('id')}<br>"
                            f"<strong>Original Reporter:</strong> {reporter}<br>"
                            f"<strong>Original Date:</strong> {original_date}<br>"
                            f"<strong>Original Assigned To:</strong> {handler_name}<br>"
                            f"<strong>Original Status:</strong> {bug.get('status_label')} ({target_state})<br>"
                            f"<strong>Original Priority:</strong> {bug.get('priority_label')}<br>"
                            f"<strong>Original Severity:</strong> {bug.get('severity_label')}<br>"
                        )
                        
                        meta_patch = [
                            JsonPatchOperation(op="add", path="/fields/System.History", value=meta_comment)
                        ]
                        wit_client.update_work_item(document=meta_patch, id=wi.id)
                        
                        # Step 2: Update to Target State
                        if target_state != "New":
                            state_patch = [JsonPatchOperation(op="add", path="/fields/System.State", value=target_state)]
                            wit_client.update_work_item(document=state_patch, id=wi.id)
                            print(f"  -> Updated State to: {target_state}")

                     except Exception as retry_err:
                        print(f"  -> Creation failed on retry: {retry_err}")
                        continue
                else:
                    print(f"  -> Creation failed: {e}")
                    continue

        # Process Attachments
        # To avoid duplicates, we check existing relations for our custom comment marker
        current_relations = wi.relations if wi.relations else []
        existing_file_ids = set()
        for rel in current_relations:
            if rel.rel == "AttachedFile" and rel.attributes and "comment" in rel.attributes:
                # We store "Imported from Mantis (ID: <file_id>)" in the comment
                comment = rel.attributes["comment"]
                if "Imported from Mantis (ID: " in comment:
                    try:
                        fid = comment.split("(ID: ")[1].split(")")[0]
                        existing_file_ids.add(fid)
                    except IndexError:
                        pass

        attachments = bug.get('attachments', [])
        if attachments and args.attachments_dir:
            print(f"  -> Processing {len(attachments)} attachments...")
            for att in attachments:
                file_id = str(att.get('file_id'))
                if file_id in existing_file_ids:
                    print(f"    -> Skipping existing attachment {att.get('filename')} (Mantis File ID: {file_id})")
                    continue

                att_path = att.get('path')
                full_path = os.path.join(args.attachments_dir, att_path)
                
                if os.path.exists(full_path):
                    try:
                        with open(full_path, "rb") as f:
                            attachment_reference = wit_client.create_attachment(upload_stream=f, file_name=att.get('filename'))
                            
                            # Add relation
                            att_patch = [
                                JsonPatchOperation(
                                    op="add",
                                    path="/relations/-",
                                    value={
                                        "rel": "AttachedFile",
                                        "url": attachment_reference.url,
                                        "attributes": {
                                            "comment": f"Imported from Mantis (ID: {file_id})"
                                        }
                                    }
                                )
                            ]
                            wit_client.update_work_item(document=att_patch, id=wi.id)
                            print(f"    -> Attached: {att.get('filename')}")
                    except Exception as att_err:
                        print(f"    -> Failed to attach {att.get('filename')}: {att_err}")

        # Process Comments (Bugnotes) - Append-only logic is tricky. 
        # Simplest approach: Add them. If it's an update, you might duplicate.
        # Refined approach: Only add comments if creating new item.
        if not existing_id: 
            bugnotes = bug.get('bugnotes', [])
            if bugnotes:
                print(f"  -> Adding {len(bugnotes)} comments...")
                bugnotes.sort(key=lambda x: x.get('date_submitted', 0))
                for note in bugnotes:
                    note_date = format_timestamp(note.get('date_submitted'))
                    note_author = format_user(note.get('reporter'))
                    note_text = note.get('note_text', '').replace("\n", "<br>")
                    
                    comment_body = (
                        f"<strong>[Comment by {note_author} on {note_date}]</strong><br>"
                        f"{note_text}"
                    )
                    
                    comment_patch = [
                        JsonPatchOperation(
                            op="add",
                            path="/fields/System.History",
                            value=comment_body
                        )
                    ]
                    wit_client.update_work_item(document=comment_patch, id=wi.id)
                print("  -> Comments added.")
        elif args.force_update:
             print("  -> existing comments skipped to avoid duplication (logic can be improved).")

if __name__ == "__main__":
    main()
