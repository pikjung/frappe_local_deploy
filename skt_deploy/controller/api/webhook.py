import frappe
from skt_deploy.services.deploy_note import DeployNoteService


@frappe.whitelist(allow_guest=True)
def skt_dev_webhook():
    token = frappe.local.request.headers.get("X-Gitlab-Token")
    secret = frappe.conf.get("gitlab_webhook_secret", "")
    payload = frappe.form_dict
    return DeployNoteService().deploy_note(token, secret, payload)