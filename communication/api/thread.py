import frappe


def ensure_contact_thread(doc, method=None):
    if not doc.name or frappe.db.get_value("Contact", doc.name, "communication_thread"):
        return
    if frappe.db.exists("Communication Thread", {"contact": doc.name}):
        thread = frappe.db.get_value("Communication Thread", {"contact": doc.name}, "name")
    else:
        thread = frappe.get_doc({
            "doctype": "Communication Thread",
            "contact": doc.name,
            "status": "Open",
        }).insert(ignore_permissions=True).name
    frappe.db.set_value("Contact", doc.name, "communication_thread", thread, update_modified=False)
