import base64
import hashlib
import json
import os
import secrets
from datetime import datetime, timedelta

import frappe
from frappe.utils import get_datetime, now_datetime


STALE_AFTER_SECONDS = 35
MAX_SIGNAL_BYTES = 200000


def _json(value):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return value
    return value


def _session(name):
    return frappe.get_doc("Call Session", name)


def _check_token(doc, token):
    if not token or not doc.join_token:
        frappe.throw("Invalid call token", frappe.PermissionError)
    if not secrets.compare_digest(str(doc.join_token), str(token)):
        frappe.throw("Invalid call token", frappe.PermissionError)


def _check_participant(doc, participant_token):
    if frappe.session.user != "Guest" and frappe.session.user == doc.initiator_user and participant_token == "owner":
        return
    if doc.guest_participant_token and participant_token and secrets.compare_digest(str(doc.guest_participant_token), str(participant_token)):
        return
    frappe.throw("Invalid participant", frappe.PermissionError)


def _get_thread(contact):
    thread = frappe.db.get_value("Communication Thread", {"contact": contact}, "name")
    if thread:
        return thread
    thread = frappe.get_doc({"doctype": "Communication Thread", "contact": contact, "status": "Open"}).insert(ignore_permissions=True)
    frappe.db.set_value("Contact", contact, "communication_thread", thread.name, update_modified=False)
    return thread.name


@frappe.whitelist()
def create_call(contact, guest_name=None):
    if frappe.session.user == "Guest":
        frappe.throw("Login is required to start a call.", frappe.PermissionError)
    if not frappe.db.exists("Contact", contact):
        frappe.throw("Contact not found")
    thread = _get_thread(contact)
    token = secrets.token_urlsafe(32)
    doc = frappe.get_doc({
        "doctype": "Call Session",
        "communication_thread": thread,
        "contact": contact,
        "initiator_user": frappe.session.user,
        "guest_name": guest_name or "Guest",
        "join_token": token,
        "guest_participant_token": None,
        "status": "Created",
        "recording_status": "Not Started",
    }).insert(ignore_permissions=True)
    frappe.db.commit()
    return {"call": doc.name, "token": token, "join_url": f"/call?token={token}"}


@frappe.whitelist(allow_guest=True)
def get_call(token):
    doc = frappe.get_doc("Call Session", {"join_token": token}) if frappe.db.exists("Call Session", {"join_token": token}) else None
    if not doc:
        frappe.throw("Call not found", frappe.DoesNotExistError)
    if doc.status in ("Completed", "Failed"):
        frappe.throw("This call has ended")
    return {
        "name": doc.name,
        "contact": doc.contact,
        "thread": doc.communication_thread,
        "status": doc.status,
        "initiator_user": doc.initiator_user,
        "guest_name": doc.guest_name,
        "is_owner": frappe.session.user != "Guest" and frappe.session.user == doc.initiator_user,
    }


@frappe.whitelist(allow_guest=True)
def join_call(token, display_name=None):
    doc = frappe.get_doc("Call Session", {"join_token": token}) if frappe.db.exists("Call Session", {"join_token": token}) else None
    if not doc:
        frappe.throw("Call not found", frappe.DoesNotExistError)
    _check_token(doc, token)
    is_owner = frappe.session.user != "Guest" and frappe.session.user == doc.initiator_user
    participant_token = "owner" if is_owner else None
    if not is_owner:
        if doc.guest_participant_token:
            participant_token = doc.guest_participant_token
        else:
            participant_token = secrets.token_urlsafe(24)
            doc.guest_participant_token = participant_token
            if display_name:
                doc.guest_name = display_name[:140]
    if doc.status == "Created":
        doc.status = "Active"
        doc.started_at = now_datetime()
        doc.last_heartbeat = now_datetime()
        doc.recording_status = "Recording"
        doc.save(ignore_permissions=True)
    elif doc.status == "Active":
        doc.last_heartbeat = now_datetime()
        doc.save(ignore_permissions=True, ignore_version=True)
    frappe.db.commit()
    return {"name": doc.name, "status": doc.status, "initiator_user": doc.initiator_user, "participant_token": participant_token, "is_owner": is_owner}


@frappe.whitelist(allow_guest=True)
def send_signal(token, kind, payload, participant_token=None):
    doc = frappe.get_doc("Call Session", {"join_token": token}) if frappe.db.exists("Call Session", {"join_token": token}) else None
    if not doc:
        frappe.throw("Call not found", frappe.DoesNotExistError)
    _check_token(doc, token)
    _check_participant(doc, participant_token)
    payload = _json(payload)
    raw = json.dumps(payload, separators=(",", ":"))
    if len(raw.encode("utf-8")) > MAX_SIGNAL_BYTES:
        frappe.throw("Signal payload is too large")
    name = frappe.generate_hash(length=12)
    sender = "owner" if frappe.session.user != "Guest" and frappe.session.user == doc.initiator_user else "guest"
    frappe.get_doc({
        "doctype": "Call Signal",
        "call_session": doc.name,
        "signal_id": name,
        "sender": sender,
        "kind": kind,
        "payload": raw,
    }).insert(ignore_permissions=True)
    frappe.db.commit()
    return {"signal_id": name}


@frappe.whitelist(allow_guest=True)
def poll_signals(token, after=None, participant_token=None):
    doc = frappe.get_doc("Call Session", {"join_token": token}) if frappe.db.exists("Call Session", {"join_token": token}) else None
    if not doc:
        frappe.throw("Call not found", frappe.DoesNotExistError)
    _check_token(doc, token)
    _check_participant(doc, participant_token)
    filters = {"call_session": doc.name}
    signals = frappe.get_all("Call Signal", filters=filters, fields=["signal_id", "sender", "kind", "payload", "creation"], order_by="creation asc")
    out = []
    found_after = after is None
    for row in signals:
        if not found_after:
            if row.signal_id == after:
                found_after = True
            continue
        try:
            payload = json.loads(row.payload)
        except Exception:
            continue
        out.append({"id": row.signal_id, "kind": row.kind, "payload": payload, "sender": row.sender, "creation": str(row.creation)})
    return out


@frappe.whitelist(allow_guest=True)
def heartbeat(token, participant_token=None):
    doc = frappe.get_doc("Call Session", {"join_token": token}) if frappe.db.exists("Call Session", {"join_token": token}) else None
    if not doc:
        frappe.throw("Call not found", frappe.DoesNotExistError)
    _check_token(doc, token)
    _check_participant(doc, participant_token)
    if doc.status in ("Created", "Active"):
        doc.status = "Active"
        doc.last_heartbeat = now_datetime()
        if not doc.started_at:
            doc.started_at = now_datetime()
        doc.save(ignore_permissions=True, ignore_version=True)
        frappe.db.commit()
    return {"status": doc.status}


@frappe.whitelist(allow_guest=True)
def upload_chunk(token, sequence, data, mime_type="audio/webm", participant_token=None):
    doc = frappe.get_doc("Call Session", {"join_token": token}) if frappe.db.exists("Call Session", {"join_token": token}) else None
    if not doc:
        frappe.throw("Call not found", frappe.DoesNotExistError)
    _check_token(doc, token)
    _check_participant(doc, participant_token)
    if not data:
        frappe.throw("Empty recording chunk")
    try:
        binary = base64.b64decode(data)
    except Exception:
        frappe.throw("Invalid recording data")
    if len(binary) > 15 * 1024 * 1024:
        frappe.throw("Recording chunk is too large")
    seq = int(sequence)
    if frappe.db.exists("Call Recording Chunk", {"call_session": doc.name, "sequence": seq}):
        return {"ok": True, "duplicate": True}
    file_doc = frappe.get_doc({
        "doctype": "File",
        "file_name": f"{doc.name}-{seq:06d}.webm",
        "content": binary,
        "attached_to_doctype": "Call Session",
        "attached_to_name": doc.name,
        "is_private": 1,
    }).insert(ignore_permissions=True)
    chunk = frappe.get_doc({
        "doctype": "Call Recording Chunk",
        "call_session": doc.name,
        "sequence": seq,
        "file": file_doc.name,
        "bytes": len(binary),
        "mime_type": mime_type,
    }).insert(ignore_permissions=True)
    frappe.db.set_value("Call Session", doc.name, {"recording_status": "Recording", "recording_bytes": (doc.recording_bytes or 0) + len(binary)}, update_modified=False)
    frappe.db.commit()
    return {"ok": True, "chunk": chunk.name}


@frappe.whitelist(allow_guest=True)
def finalize_call(token, duration_seconds=None, end_reason="normal", final_data=None, mime_type="audio/webm", participant_token=None):
    doc = frappe.get_doc("Call Session", {"join_token": token}) if frappe.db.exists("Call Session", {"join_token": token}) else None
    if not doc:
        frappe.throw("Call not found", frappe.DoesNotExistError)
    _check_token(doc, token)
    _check_participant(doc, participant_token)
    chunks = frappe.get_all("Call Recording Chunk", filters={"call_session": doc.name}, fields=["sequence", "file", "bytes", "mime_type"], order_by="sequence asc")
    if final_data:
        try:
            binary = base64.b64decode(final_data)
        except Exception:
            frappe.throw("Invalid final recording data")
        if len(binary) > 200 * 1024 * 1024:
            frappe.throw("Final recording is too large")
    elif chunks:
        parts = []
        total = 0
        for chunk in chunks:
            f = frappe.get_doc("File", chunk.file)
            file_url = f.file_url or ""
            if file_url.startswith("/"):
                path = frappe.get_site_path(file_url.lstrip("/"))
            else:
                path = frappe.get_site_path("public", file_url.lstrip("/"))
            if os.path.exists(path):
                with open(path, "rb") as fp:
                    data = fp.read()
                parts.append(data)
                total += len(data)
        binary = b"".join(parts)
        if not binary:
            doc.recording_status = "Partial"
        else:
            file_doc = frappe.get_doc({
                "doctype": "File",
                "file_name": f"{doc.name}.webm",
                "content": binary,
                "attached_to_doctype": "Call Session",
                "attached_to_name": doc.name,
                "is_private": 1,
            }).insert(ignore_permissions=True)
            doc.recording_file = file_doc.name
            doc.recording_bytes = len(binary)
            doc.recording_mime_type = mime_type or chunks[0].mime_type or "audio/webm"
            doc.recording_status = "Completed" if end_reason == "normal" else "Partial"
    else:
        doc.recording_status = "Failed"
    if final_data:
        file_doc = frappe.get_doc({
            "doctype": "File",
            "file_name": f"{doc.name}.webm",
            "content": binary,
            "attached_to_doctype": "Call Session",
            "attached_to_name": doc.name,
            "is_private": 1,
        }).insert(ignore_permissions=True)
        doc.recording_file = file_doc.name
        doc.recording_bytes = len(binary)
        doc.recording_mime_type = mime_type
        doc.recording_status = "Completed"
    doc.status = "Completed" if end_reason == "normal" else "Interrupted"
    doc.ended_at = now_datetime()
    doc.last_heartbeat = now_datetime()
    doc.end_reason = (end_reason or "normal")[:140]
    if duration_seconds is not None:
        try:
            doc.duration_seconds = max(0, int(duration_seconds))
        except Exception:
            pass
    elif doc.started_at:
        doc.duration_seconds = max(0, int((get_datetime(doc.ended_at) - get_datetime(doc.started_at)).total_seconds()))
    doc.save(ignore_permissions=True)
    communication = _create_communication(doc)
    frappe.db.commit()
    return {"status": doc.status, "recording_status": doc.recording_status, "recording_file": doc.recording_file, "communication": communication}


def _create_communication(doc):
    if frappe.db.exists("Communication", {"call_session": doc.name}):
        return frappe.db.get_value("Communication", {"call_session": doc.name}, "name")
    meta = frappe.get_meta("Communication")
    values = {
        "doctype": "Communication",
        "subject": f"Browser Call with {doc.contact}",
        "content": f"1-to-1 browser call. Duration: {doc.duration_seconds or 0} seconds. Recording: {doc.recording_file or 'Partial/Unavailable'}.",
    }
    optional = {
        "communication_type": "Communication",
        "communication_medium": "Phone",
        "reference_doctype": "Contact",
        "reference_name": doc.contact,
        "communication_thread": doc.communication_thread,
        "call_session": doc.name,
        "user": doc.initiator_user,
    }
    for field, value in optional.items():
        if meta.has_field(field):
            values[field] = value
    communication = frappe.get_doc(values).insert(ignore_permissions=True)
    frappe.db.set_value("Communication Thread", doc.communication_thread, "last_communication_at", communication.creation, update_modified=False)
    return communication.name


def mark_stale_calls():
    cutoff = now_datetime() - timedelta(seconds=STALE_AFTER_SECONDS)
    calls = frappe.get_all("Call Session", filters={"status": "Active", "last_heartbeat": ["<", cutoff]}, pluck="name")
    for name in calls:
        doc = frappe.get_doc("Call Session", name)
        if doc.status != "Active":
            continue
        doc.status = "Interrupted"
        doc.end_reason = "Heartbeat timeout"
        doc.ended_at = now_datetime()
        if doc.started_at:
            doc.duration_seconds = max(0, int((get_datetime(doc.ended_at) - get_datetime(doc.started_at)).total_seconds()))
        doc.recording_status = "Partial" if frappe.db.exists("Call Recording Chunk", {"call_session": name}) else "Failed"
        doc.save(ignore_permissions=True)
        _create_communication(doc)
    frappe.db.commit()
