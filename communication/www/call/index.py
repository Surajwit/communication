from frappe.sessions import get_csrf_token


def get_context(context):
    context.csrf_token = get_csrf_token()