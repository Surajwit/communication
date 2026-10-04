frappe.ui.form.on("Call Session", {
  refresh(frm) {
    if (frm.doc.recording_file) {
      frm.add_custom_button(__("Open Recording"), () => {
        frappe.db.get_value("File", frm.doc.recording_file, "file_url", r => {
          if (r?.file_url) window.open(r.file_url, "_blank");
        });
      });
    }
  }
});
