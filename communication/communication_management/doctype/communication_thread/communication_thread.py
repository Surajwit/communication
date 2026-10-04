import frappe
from frappe.model.document import Document


class CommunicationThread(Document):
    def validate(self):
        if self.contact:
            existing = frappe.db.get_value("Communication Thread", {"contact": self.contact}, "name")
            if existing and existing != self.name:
                frappe.throw("This Contact already has a Communication Thread.")
