"""Recognize explicit cross-document references in MCP JSON payloads.

Diagnostic helper only; not an authorization boundary. Raw MCP audit access
requires full visibility regardless of this classification. This does not infer
patient data from arbitrary prose or bare phone-like strings.
"""
import json
import frappe
from privacy_shield.import_access import TARGETS

FIELDS = ("request_summary_json", "response_summary_json", "diff_json")
REFERENCE_KEYS = ("doctype", "ref_doctype", "reference_doctype", "document_type")
MAX_BYTES = 65536


def has_protected_reference(doc):
    for field in FIELDS:
        raw = doc.get(field)
        if not raw:
            continue
        if len(raw.encode("utf-8")) > MAX_BYTES:
            return True
        try:
            pending = [json.loads(raw)]
        except (ValueError, TypeError, RecursionError):
            return True
        while pending:
            item = pending.pop()
            if isinstance(item, dict):
                if any(isinstance(item.get(key), str) and item[key] in TARGETS for key in REFERENCE_KEYS):
                    return True
                pending.extend(item.values())
            elif isinstance(item, list):
                pending.extend(item)
    return False


def query_condition():
    # MariaDB checks mirror the document check, with invalid/oversized payloads
    # withheld. No values are fetched into application memory for list filtering.
    valid = []
    sources = []
    for field in FIELDS:
        col = f"`tabMCP Audit Log`.`{field}`"
        valid.append(f"({col} IS NULL OR {col} = '' OR (OCTET_LENGTH({col}) <= {MAX_BYTES} AND JSON_VALID({col})))")
        sources.append(f"JSON_EXTRACT(CASE WHEN JSON_VALID({col}) THEN {col} ELSE '{{}}' END, '$')")
    combined = "JSON_ARRAY(" + ",".join(sources) + ")"
    paths = ",".join(frappe.db.escape("$**." + key) for key in REFERENCE_KEYS)
    absent = [f"JSON_SEARCH({combined}, 'one', {frappe.db.escape(target)}, NULL, {paths}) IS NULL" for target in TARGETS]
    return " AND ".join(valid + absent)
