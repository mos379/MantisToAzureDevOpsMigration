#!/usr/bin/env python3
import argparse
import os
import re
import sys


def read_first_assignment(path, var_name):
    if not os.path.exists(path):
        return None
    pattern = re.compile(r"^\s*\$" + re.escape(var_name) + r"\s*=\s*([^;]+);")
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            m = pattern.match(line)
            if m:
                return m.group(1).strip()
    return None


def parse_php_value(raw):
    if raw is None:
        return None
    if raw.startswith("'") and raw.endswith("'"):
        return raw[1:-1]
    if raw.isdigit():
        return int(raw)
    return raw


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


def main():
    ap = argparse.ArgumentParser(description="Verify MantisMigrationTool repo setup.")
    ap.add_argument("--project", default="ITs4BM", help="Project folder under source/")
    args = ap.parse_args()

    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    source_root = os.path.join(root, "source", args.project)
    sql_path = os.path.join(source_root, "mantisbt.sql")
    mantis_root = os.path.join(source_root, "mantisbt")
    defaults_path = os.path.join(mantis_root, "config_defaults_inc.php")
    override_path = os.path.join(mantis_root, "config_inc.php")

    errors = []
    warnings = []

    if not os.path.exists(source_root):
        errors.append(f"Missing project source folder: {source_root}")
    if not os.path.exists(sql_path):
        errors.append(f"Missing SQL dump: {sql_path}")
    if not os.path.exists(mantis_root):
        errors.append(f"Missing MantisBT folder: {mantis_root}")
    if not os.path.exists(defaults_path):
        errors.append(f"Missing defaults config: {defaults_path}")

    file_upload_method = parse_php_value(read_first_assignment(override_path, "g_file_upload_method"))
    if file_upload_method is None:
        file_upload_method = parse_php_value(read_first_assignment(defaults_path, "g_file_upload_method"))

    file_path = parse_php_value(read_first_assignment(override_path, "g_file_path"))
    if file_path is None:
        file_path = parse_php_value(read_first_assignment(defaults_path, "g_file_path"))

    if file_upload_method in ("DISK", "FTP"):
        if file_path:
            norm_path = file_path.replace("%absolute_path%", mantis_root + os.sep)
            norm_path = os.path.abspath(os.path.expanduser(norm_path))
            if not norm_path.startswith(os.path.abspath(mantis_root)):
                warnings.append(
                    "File upload method is DISK/FTP and file path is outside Mantis folder: "
                    f"{norm_path}"
                )
        else:
            warnings.append("File upload method is DISK/FTP but g_file_path is not set.")
    elif file_upload_method == "DATABASE":
        if os.path.exists(sql_path):
            try:
                attach_count = 0
                with open(sql_path, "r", encoding="utf-8", errors="replace") as f:
                    for line in f:
                        if line.startswith("INSERT INTO `mantis_bug_file_table` VALUES"):
                            attach_count += line.count("(")
                if attach_count == 0:
                    warnings.append("No attachments found in mantis_bug_file_table.")
                else:
                    print(f"Attachments in DB: {attach_count}")
            except OSError as e:
                warnings.append(f"Failed to scan SQL for attachments: {e}")

    required_enum_vars = [
        "g_priority_enum_string",
        "g_severity_enum_string",
        "g_reproducibility_enum_string",
        "g_status_enum_string",
        "g_resolution_enum_string",
        "g_projection_enum_string",
        "g_eta_enum_string",
        "g_view_state_enum_string",
        "g_project_status_enum_string",
        "g_project_view_state_enum_string",
    ]
    enum_missing = []
    for var in required_enum_vars:
        val = read_first_assignment(override_path, var)
        if val is None:
            val = read_first_assignment(defaults_path, var)
        if val is None:
            enum_missing.append(var)
    if enum_missing:
        warnings.append("Missing enum definitions: " + ", ".join(enum_missing))

    constants_path = os.path.join(mantis_root, "core", "constant_inc.php")
    if not os.path.exists(constants_path):
        warnings.append(f"Missing constants file: {constants_path}")
    else:
        constants = load_constants(constants_path)
        required_constants = ["BUGNOTE", "REMINDER", "TIME_TRACKING"]
        missing_constants = [c for c in required_constants if c not in constants]
        if missing_constants:
            warnings.append("Missing bugnote constants: " + ", ".join(missing_constants))

    print("Repo setup check")
    if errors:
        print("Errors:")
        for e in errors:
            print(f"- {e}")
    if warnings:
        print("Warnings:")
        for w in warnings:
            print(f"- {w}")

    if errors:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
