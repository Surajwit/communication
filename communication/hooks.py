app_name = "communication"
app_title = "Communication"
app_publisher = "Communication"
app_description = "1-to-1 browser communication and communication threads for Frappe"
app_email = "support@example.com"
app_license = "MIT"
app_version = "0.1.1"

required_apps = ["frappe"]

fixtures = [
    {
        "dt": "Custom Field",
        "filters": [
            [
                "name",
                "in",
                [
                    "Contact-communication_thread",
                    "Communication-communication_thread",
                    "Communication-call_session",
                ],
            ]
        ],
    }
]


add_to_apps_screen = [{
    "name": "communication",
    "title": "Communication",
    "route": "/app/communication-thread"
}]

doc_events = {
    "Contact": {
        "after_insert": "communication.api.thread.ensure_contact_thread"
    }
}

doctype_js = {
    "Contact": "public/js/contact.js",
    "Communication Thread": "public/js/communication_thread.js",
    "Call Session": "public/js/call_session.js",
}

scheduler_events = {
    "cron": {
        "*/1 * * * *": ["communication.api.call.mark_stale_calls"]
    }
}
