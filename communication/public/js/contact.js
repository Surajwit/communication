frappe.ui.form.on("Contact", {
  refresh(frm) {
    if (frm.is_new()) return;
    frm.add_custom_button(__("Start Browser Call"), () => {
      frappe.call({
        method: "communication.api.call.create_call",
        args: { contact: frm.doc.name, guest_name: frm.doc.first_name || frm.doc.name },
        callback(r) {
          if (!r.message) return;
          const url = `${window.location.origin}${r.message.join_url}`;
          const dialog = new frappe.ui.Dialog({
            title: __("Browser Call"),
            fields: [
              { fieldname: "url", fieldtype: "Data", label: __("Join URL"), read_only: 1, default: url },
            ],
            primary_action_label: __("Open Call"),
            primary_action() { window.open(url, "_blank"); dialog.hide(); }
          });
          dialog.show();
          dialog.fields_dict.url.$input.on("click", function() { this.select(); });
        }
      });
    }, __("Communication"));
  }
});
