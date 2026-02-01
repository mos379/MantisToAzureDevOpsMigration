#!/usr/bin/env python3
import argparse
import csv
import os
import re


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


def iter_bug_file_rows(sql_path):
    with open(sql_path, "r", encoding="latin-1", errors="replace") as f:
        buf = ""
        collecting = False
        for line in f:
            if not collecting:
                if line.startswith("INSERT INTO `mantis_bug_file_table` VALUES"):
                    collecting = True
                    buf = line.strip()
            else:
                buf += line.strip()

            if collecting and buf.endswith(";"):
                values_part = buf.split("VALUES", 1)[1].strip()
                for row in parse_values(values_part):
                    yield row
                collecting = False
                buf = ""


def sanitize_filename(name):
    name = name.replace("\\", "_").replace("/", "_")
    name = re.sub(r"\s+", " ", name).strip()
    return name or "attachment"


def row_to_fields(row):
    if len(row) >= 12 and isinstance(row[9], str):
        return {
            "id": row[0],
            "bug_id": row[1],
            "title": row[2],
            "description": row[3],
            "diskfile": row[4],
            "filename": row[5],
            "folder": row[6],
            "filesize": row[7],
            "file_type": row[8],
            "content": row[9],
            "date_added": row[10],
            "user_id": row[11],
        }
    if len(row) == 11 and isinstance(row[10], str):
        return {
            "id": row[0],
            "bug_id": row[1],
            "title": row[2],
            "description": row[3],
            "diskfile": row[4],
            "filename": row[5],
            "folder": row[6],
            "filesize": row[7],
            "file_type": row[8],
            "date_added": row[9],
            "content": row[10],
        }
    if len(row) == 10:
        return {
            "id": row[0],
            "bug_id": row[1],
            "title": row[2],
            "description": row[3],
            "diskfile": row[4],
            "filename": row[5],
            "folder": row[6],
            "filesize": row[7],
            "file_type": row[8],
            "content": row[9],
        }
    return None


def main():
    ap = argparse.ArgumentParser(description="Export Mantis attachments from SQL dump.")
    ap.add_argument("--sql", default="source/ITs4BM/mantisbt.sql", help="Path to Mantis SQL dump")
    ap.add_argument("--output", default="export/attachments", help="Output folder")
    args = ap.parse_args()

    os.makedirs(args.output, exist_ok=True)
    manifest_path = os.path.join(args.output, "manifest.csv")

    written = 0
    skipped = 0
    with open(manifest_path, "w", encoding="utf-8", newline="") as mf:
        writer = csv.DictWriter(
            mf,
            fieldnames=[
                "file_id",
                "bug_id",
                "filename",
                "diskfile",
                "filesize",
                "file_type",
                "title",
                "description",
                "path",
            ],
        )
        writer.writeheader()

        for row in iter_bug_file_rows(args.sql):
            fields = row_to_fields(row)
            if not fields:
                skipped += 1
                continue

            bug_id = fields.get("bug_id")
            file_id = fields.get("id")
            filename = sanitize_filename(str(fields.get("filename") or "attachment"))
            subdir = os.path.join(args.output, f"bug_{bug_id}")
            os.makedirs(subdir, exist_ok=True)
            out_name = f"{file_id}_{filename}"
            out_path = os.path.join(subdir, out_name)

            content = fields.get("content")
            if content is None:
                skipped += 1
                continue
            data = content.encode("latin-1")
            with open(out_path, "wb") as out:
                out.write(data)

            writer.writerow(
                {
                    "file_id": file_id,
                    "bug_id": bug_id,
                    "filename": fields.get("filename"),
                    "diskfile": fields.get("diskfile"),
                    "filesize": fields.get("filesize"),
                    "file_type": fields.get("file_type"),
                    "title": fields.get("title"),
                    "description": fields.get("description"),
                    "path": os.path.relpath(out_path, args.output),
                }
            )
            written += 1

    print(f"Wrote {written} attachments to {args.output}")
    if skipped:
        print(f"Skipped {skipped} rows (unexpected format or empty content)")
    print(f"Manifest: {manifest_path}")


if __name__ == "__main__":
    raise SystemExit(main())
