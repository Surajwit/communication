frappe.ui.form.on("Communication Thread", {
  refresh(frm) {
    if (frm.doc.contact) {
      frm.add_custom_button(__("Open Contact"), () => frappe.set_route("Form", "Contact", frm.doc.contact));
    }
  }
});
