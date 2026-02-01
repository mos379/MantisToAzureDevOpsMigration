#!/usr/bin/env python3
import argparse
import datetime as dt
import json
import os
import re
import csv

TABLE_COLUMNS = {
    "mantis_bug_table": [
        "id","project_id","reporter_id","handler_id","duplicate_id","priority","severity",
        "reproducibility","status","resolution","projection","eta","bug_text_id","os",
        "os_build","platform","version","fixed_in_version","build","profile_id","view_state",
        "summary","sponsorship_total","sticky","target_version","category_id","date_submitted",
        "due_date","last_updated",
    ],
    "mantis_bug_text_table": ["id","description","steps_to_reproduce","additional_information"],
    "mantis_bugnote_table": [
        "id","bug_id","reporter_id","bugnote_text_id","view_state","note_type","note_attr",
        "time_tracking","last_modified","date_submitted",
    ],
    "mantis_bugnote_text_table": ["id","note"],
    "mantis_user_table": [
        "id","username","realname","email","password","enabled","protected","access_level",
        "login_count","lost_password_request_count","failed_login_count","cookie_string",
        "last_visit","date_created",
    ],
    "mantis_category_table": ["id","project_id","user_id","name","status"],
    "mantis_project_table": [
        "id","name","status","enabled","view_state","access_min","file_path","description",
        "category_id","inherit_global",
    ],
    "mantis_bug_relationship_table": [
        "id","source_bug_id","destination_bug_id","relationship_type",
    ],
    "mantis_bug_history_table": [
        "id","user_id","bug_id","field_name","old_value","new_value","type","date_modified",
    ],
    "mantis_tag_table": ["id","user_id","name","description","date_created","date_updated"],
    "mantis_bug_tag_table": ["bug_id","tag_id","user_id","date_attached"],
}


def epoch_to_iso(ts):
    try:
        ts = int(ts)
    except (TypeError, ValueError):
        return ""
    if ts <= 1:
        return ""
    return dt.datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%SZ")


def parse_values(values_blob):
    rows = []
    cur = []
    token = ""
    token_is_string = False
    pending_value = False
    in_string = False
    escape = False

    def push_token():
        nonlocal token, token_is_string, pending_value, cur
        if not (pending_value or token.strip() != ""):
            return
        if token_is_string:
            val = token
        else:
            t = token.strip()
            if t.upper() == "NULL":
                val = None
            elif t == "":
                val = ""
            else:
                try:
                    val = int(t)
                except ValueError:
                    try:
                        val = float(t)
                    except ValueError:
                        val = t
        cur.append(val)
        token = ""
        token_is_string = False
        pending_value = False

    i = 0
    n = len(values_blob)
    while i < n:
        ch = values_blob[i]
        if in_string:
            if escape:
                if ch == "n":
                    token += "\n"
                elif ch == "r":
                    token += "\r"
                elif ch == "t":
                    token += "\t"
                elif ch == "0":
                    token += "\0"
                elif ch == "Z":
                    token += "\x1a"
                else:
                    token += ch
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == "'":
                in_string = False
                token_is_string = True
                pending_value = True
            else:
                token += ch
            i += 1
            continue

        if ch == "'":
            in_string = True
            token = ""
            token_is_string = True
            pending_value = False
            i += 1
            continue
        if ch == "(":
            cur = []
            token = ""
            token_is_string = False
            pending_value = False
            i += 1
            continue
        if ch == ",":
            push_token()
            i += 1
            continue
        if ch == ")":
            push_token()
            if cur:
                rows.append(cur)
            cur = []
            i += 1
            continue
        if ch == ";":
            break
        token += ch
        i += 1

    return rows


def load_table_inserts(sql_path, tables):
    data = {t: [] for t in tables}
    with open(sql_path, "r", encoding="utf-8", errors="replace") as f:
        buf = ""
        current_table = None
        for line in f:
            if current_table is None:
                for t in tables:
                    marker = f"INSERT INTO `{t}` VALUES"
                    if line.startswith(marker):
                        current_table = t
                        buf = line.strip()
                        break
            else:
                buf += line.strip()

            if current_table and buf.endswith(";"):
                values_part = buf.split("VALUES", 1)[1].strip()
                rows = parse_values(values_part)
                data[current_table].extend(rows)
                current_table = None
                buf = ""
    return data


def load_enum_strings(defaults_path, override_path):
    enum_strings = {}
    pattern = re.compile(r"^\s*\$g_(\w+_enum_string)\s*=\s*'([^']*)';")

    def read_file(path):
        if not path or not os.path.exists(path):
            return
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                m = pattern.match(line)
                if m:
                    enum_strings[m.group(1)] = m.group(2)

    read_file(defaults_path)
    read_file(override_path)
    return enum_strings


def parse_enum_string(s):
    out = {}
    if not s:
        return out
    for part in s.split(","):
        part = part.strip()
        if not part:
            continue
        if ":" not in part:
            continue
        key_str, label = part.split(":", 1)
        key_str = key_str.strip()
        label = label.strip()
        try:
            key = int(key_str)
        except ValueError:
            key = key_str
        out[key] = label
    return out


def map_label(enum_map, value):
    if value is None or enum_map is None:
        return ""
    try:
        key = int(value)
    except (TypeError, ValueError):
        key = value
    return enum_map.get(key, "")


def load_constants(path):
    constants = {}
    if not path or not os.path.exists(path):
        return constants
    pattern = re.compile(r"^\s*define\(\s*'([^']+)'\s*,\s*([0-9]+)\s*\);\s*$")
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            m = pattern.match(line)
            if m:
                constants[m.group(1)] = int(m.group(2))
    return constants


def rows_to_dict(table, raw):
    cols = TABLE_COLUMNS[table]
    out = {}
    for row in raw.get(table, []):
        row = row + [None] * (len(cols) - len(row))
        item = {cols[i]: row[i] for i in range(len(cols))}
        out[item[cols[0]]] = item
    return out


def main():
    ap = argparse.ArgumentParser(description="Extract Mantis SQL dump into JSON.")
    ap.add_argument("--sql", default="source/ITs4BM/mantisbt.sql", help="Path to Mantis SQL dump")
    ap.add_argument("--output", default="export/mantis_data.json", help="Output JSON path")
    ap.add_argument("--limit", type=int, default=0, help="Limit number of bugs exported (0 = no limit)")
    ap.add_argument("--config-defaults", default="source/ITs4BM/mantisbt/config_defaults_inc.php", help="Path to Mantis config_defaults_inc.php")
    ap.add_argument("--config-override", default="source/ITs4BM/mantisbt/config_inc.php", help="Path to Mantis config_inc.php")
    ap.add_argument("--constants-path", default="source/ITs4BM/mantisbt/core/constant_inc.php", help="Path to Mantis constant_inc.php")
    ap.add_argument("--attachments-manifest", default="export/attachments/manifest.csv", help="Path to attachments manifest CSV")
    args = ap.parse_args()

    enum_strings = load_enum_strings(args.config_defaults, args.config_override)
    enum_maps = {
        "priority": parse_enum_string(enum_strings.get("priority_enum_string", "")),
        "severity": parse_enum_string(enum_strings.get("severity_enum_string", "")),
        "reproducibility": parse_enum_string(enum_strings.get("reproducibility_enum_string", "")),
        "status": parse_enum_string(enum_strings.get("status_enum_string", "")),
        "resolution": parse_enum_string(enum_strings.get("resolution_enum_string", "")),
        "projection": parse_enum_string(enum_strings.get("projection_enum_string", "")),
        "eta": parse_enum_string(enum_strings.get("eta_enum_string", "")),
        "view_state": parse_enum_string(enum_strings.get("view_state_enum_string", "")),
        "project_status": parse_enum_string(enum_strings.get("project_status_enum_string", "")),
        "project_view_state": parse_enum_string(enum_strings.get("project_view_state_enum_string", "")),
    }
    constants = load_constants(args.constants_path)
    note_type_map = {}
    for key in ("BUGNOTE", "REMINDER", "TIME_TRACKING"):
        if key in constants:
            note_type_map[constants[key]] = key.lower()

    tables = list(TABLE_COLUMNS.keys())
    raw = load_table_inserts(args.sql, tables)

    bugs = rows_to_dict("mantis_bug_table", raw)
    bug_texts = rows_to_dict("mantis_bug_text_table", raw)
    users = rows_to_dict("mantis_user_table", raw)
    categories = rows_to_dict("mantis_category_table", raw)
    projects = rows_to_dict("mantis_project_table", raw)
    bugnote_texts = rows_to_dict("mantis_bugnote_text_table", raw)
    tags = rows_to_dict("mantis_tag_table", raw)

    def map_rows(table):
        cols = TABLE_COLUMNS[table]
        out = []
        for row in raw.get(table, []):
            row = row + [None] * (len(cols) - len(row))
            out.append({cols[i]: row[i] for i in range(len(cols))})
        return out

    bugnotes = map_rows("mantis_bugnote_table")
    relationships = map_rows("mantis_bug_relationship_table")
    history = map_rows("mantis_bug_history_table")
    bug_tags = map_rows("mantis_bug_tag_table")

    if args.limit and args.limit > 0:
        bug_ids = [k for k, _ in sorted(bugs.items(), key=lambda x: x[0])][: args.limit]
        bug_id_set = set(bug_ids)
        bugs = {k: v for k, v in bugs.items() if k in bug_id_set}

        bug_text_id_set = {b.get("bug_text_id") for b in bugs.values() if b.get("bug_text_id")}
        bug_texts = {k: v for k, v in bug_texts.items() if k in bug_text_id_set}

        bugnotes = [n for n in bugnotes if n.get("bug_id") in bug_id_set]
        bugnote_text_id_set = {n.get("bugnote_text_id") for n in bugnotes if n.get("bugnote_text_id")}
        bugnote_texts = {k: v for k, v in bugnote_texts.items() if k in bugnote_text_id_set}

        relationships = [r for r in relationships if r.get("source_bug_id") in bug_id_set]
        history = [h for h in history if h.get("bug_id") in bug_id_set]

        bug_tags = [bt for bt in bug_tags if bt.get("bug_id") in bug_id_set]
        tag_id_set = {bt.get("tag_id") for bt in bug_tags if bt.get("tag_id")}
        tags = {k: v for k, v in tags.items() if k in tag_id_set}

        project_id_set = {b.get("project_id") for b in bugs.values() if b.get("project_id")}
        projects = {k: v for k, v in projects.items() if k in project_id_set}

        category_id_set = {b.get("category_id") for b in bugs.values() if b.get("category_id")}
        categories = {k: v for k, v in categories.items() if k in category_id_set}

        user_id_set = set()
        for b in bugs.values():
            if b.get("reporter_id"):
                user_id_set.add(b.get("reporter_id"))
            if b.get("handler_id"):
                user_id_set.add(b.get("handler_id"))
        for n in bugnotes:
            if n.get("reporter_id"):
                user_id_set.add(n.get("reporter_id"))
        for h in history:
            if h.get("user_id"):
                user_id_set.add(h.get("user_id"))
        users = {k: v for k, v in users.items() if k in user_id_set}

    for n in bugnotes:
        text = bugnote_texts.get(n.get("bugnote_text_id"), {}).get("note")
        n["note_text"] = text if text is not None else ""
        reporter = users.get(n.get("reporter_id"), {})
        n["reporter"] = {
            "id": reporter.get("id"),
            "username": reporter.get("username") or "",
            "realname": reporter.get("realname") or "",
            "email": reporter.get("email") or "",
        }
        view_state_id = n.get("view_state")
        note_type_id = n.get("note_type")
        n["view_state_label"] = map_label(enum_maps.get("view_state"), view_state_id)
        n["note_type_label"] = note_type_map.get(note_type_id, "")
        ordered_keys = [
            "id",
            "bug_id",
            "reporter_id",
            "bugnote_text_id",
            "view_state",
            "view_state_label",
            "note_type",
            "note_type_label",
            "note_attr",
            "time_tracking",
            "last_modified",
            "date_submitted",
            "note_text",
            "reporter",
        ]
        reordered = {}
        for k in ordered_keys:
            if k in n:
                reordered[k] = n[k]
        for k in n.keys():
            if k not in reordered:
                reordered[k] = n[k]
        n.clear()
        n.update(reordered)

    for b in bugs.values():
        text = bug_texts.get(b.get("bug_text_id"), {})
        b["description"] = text.get("description") or ""
        b["steps_to_reproduce"] = text.get("steps_to_reproduce") or ""
        b["additional_information"] = text.get("additional_information") or ""
        reporter = users.get(b.get("reporter_id"), {})
        handler = users.get(b.get("handler_id"), {})
        b["reporter"] = {
            "id": reporter.get("id"),
            "username": reporter.get("username") or "",
            "realname": reporter.get("realname") or "",
            "email": reporter.get("email") or "",
        }
        b["handler"] = {
            "id": handler.get("id"),
            "username": handler.get("username") or "",
            "realname": handler.get("realname") or "",
            "email": handler.get("email") or "",
        }
        project = projects.get(b.get("project_id"), {})
        category = categories.get(b.get("category_id"), {})
        b["project"] = {
            "id": project.get("id"),
            "name": project.get("name") or "",
            "status": project.get("status"),
            "status_label": map_label(enum_maps.get("project_status"), project.get("status")),
            "view_state": project.get("view_state"),
            "view_state_label": map_label(enum_maps.get("project_view_state"), project.get("view_state")),
        }
        b["category"] = {
            "id": category.get("id"),
            "name": category.get("name") or "",
            "status": category.get("status"),
            "project_id": category.get("project_id"),
        }
        b["priority_label"] = map_label(enum_maps.get("priority"), b.get("priority"))
        b["severity_label"] = map_label(enum_maps.get("severity"), b.get("severity"))
        b["reproducibility_label"] = map_label(enum_maps.get("reproducibility"), b.get("reproducibility"))
        b["status_label"] = map_label(enum_maps.get("status"), b.get("status"))
        b["resolution_label"] = map_label(enum_maps.get("resolution"), b.get("resolution"))
        b["projection_label"] = map_label(enum_maps.get("projection"), b.get("projection"))
        b["eta_label"] = map_label(enum_maps.get("eta"), b.get("eta"))
        b["view_state_label"] = map_label(enum_maps.get("view_state"), b.get("view_state"))
        ordered_bug_keys = [
            "id",
            "project_id",
            "project",
            "category_id",
            "category",
            "reporter_id",
            "reporter",
            "handler_id",
            "handler",
            "duplicate_id",
            "priority",
            "priority_label",
            "severity",
            "severity_label",
            "reproducibility",
            "reproducibility_label",
            "status",
            "status_label",
            "resolution",
            "resolution_label",
            "projection",
            "projection_label",
            "eta",
            "eta_label",
            "view_state",
            "view_state_label",
            "bug_text_id",
            "summary",
            "description",
            "steps_to_reproduce",
            "additional_information",
            "os",
            "os_build",
            "platform",
            "version",
            "fixed_in_version",
            "build",
            "profile_id",
            "sponsorship_total",
            "sticky",
            "target_version",
            "date_submitted",
            "due_date",
            "last_updated",
        ]
        reordered_bug = {}
        for k in ordered_bug_keys:
            if k in b:
                reordered_bug[k] = b[k]
        for k in b.keys():
            if k not in reordered_bug:
                reordered_bug[k] = b[k]
        b.clear()
        b.update(reordered_bug)

    bugnotes_by_bug = {}
    for n in bugnotes:
        bugnotes_by_bug.setdefault(n.get("bug_id"), []).append(n)
    for bug_id, b in bugs.items():
        b["bugnotes"] = bugnotes_by_bug.get(bug_id, [])

    rels_by_bug = {}
    for r in relationships:
        rels_by_bug.setdefault(r.get("source_bug_id"), []).append(r)
    for bug_id, b in bugs.items():
        b["relationships"] = rels_by_bug.get(bug_id, [])

    history_by_bug = {}
    for h in history:
        history_by_bug.setdefault(h.get("bug_id"), []).append(h)
    for bug_id, b in bugs.items():
        b["history"] = history_by_bug.get(bug_id, [])

    tags_by_bug = {}
    for bt in bug_tags:
        bug_id = bt.get("bug_id")
        tag = tags.get(bt.get("tag_id"), {})
        if bug_id is None:
            continue
        tags_by_bug.setdefault(bug_id, []).append({
            "tag_id": bt.get("tag_id"),
            "tag_name": tag.get("name") or "",
            "tag_description": tag.get("description") or "",
            "user_id": bt.get("user_id"),
            "date_attached": bt.get("date_attached"),
        })
    for bug_id, b in bugs.items():
        b["tags"] = tags_by_bug.get(bug_id, [])

    if os.path.exists(args.attachments_manifest):
        attachments_by_bug = {}
        with open(args.attachments_manifest, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                bug_id = row.get("bug_id")
                if bug_id is None or bug_id == "":
                    continue
                try:
                    bug_id = int(bug_id)
                except ValueError:
                    continue
                attachments_by_bug.setdefault(bug_id, []).append({
                    "file_id": row.get("file_id"),
                    "filename": row.get("filename"),
                    "diskfile": row.get("diskfile"),
                    "filesize": row.get("filesize"),
                    "file_type": row.get("file_type"),
                    "title": row.get("title"),
                    "description": row.get("description"),
                    "path": row.get("path"),
                })
        for bug_id, b in bugs.items():
            b["attachments"] = attachments_by_bug.get(bug_id, [])

    bugnotes_by_id = {n.get("id"): n for n in bugnotes if n.get("id") is not None}

    payload = {
        "meta": {
            "generated_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ"),
            "source_sql": os.path.basename(args.sql),
        },
        "counts": {
            "bugs": len(bugs),
            "bug_texts": len(bug_texts),
            "bugnotes": len(bugnotes),
            "bugnote_texts": len(bugnote_texts),
            "relationships": len(relationships),
            "history": len(history),
            "projects": len(projects),
            "categories": len(categories),
            "users": len(users),
            "tags": len(tags),
            "bug_tags": len(bug_tags),
        },
        "enum_labels": enum_maps,
        "note_type_labels": note_type_map,
        "bugs_by_id": bugs,
        "bug_texts_by_id": bug_texts,
        "users_by_id": users,
        "categories_by_id": categories,
        "projects_by_id": projects,
        "bugnote_texts_by_id": bugnote_texts,
        "bugnotes_by_id": bugnotes_by_id,
        "tags_by_id": tags,
        "bugnotes": bugnotes,
        "relationships": relationships,
        "history": history,
        "bug_tags": bug_tags,
    }

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=True)

    print(f"Wrote {args.output}")


if __name__ == "__main__":
    raise SystemExit(main())
