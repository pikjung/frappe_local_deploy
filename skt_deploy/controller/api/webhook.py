import frappe
import json
import subprocess
from frappe import _
from frappe.query_builder import Table
from passlib.context import CryptContext

Auth = Table("__Auth")

passlibctx = CryptContext(
	schemes=[
		"pbkdf2_sha256",
		"argon2",
	],
)


@frappe.whitelist(allow_guest=True)
def skt_dev_webhook():
    token = frappe.local.request.headers.get("X-Gitlab-Token")
    secret = frappe.conf.get("gitlab_webhook_secret", "")
    if secret and token != secret:
        frappe.throw(_("Unauthorized"), frappe.AuthenticationError)

    event = frappe.local.request.headers.get("X-Gitlab-Event")
    if event != "Merge Request Hook":
        return {"status": "ignored", "reason": f"Event '{event}' not handled"}

    payload = frappe.form_dict

    project_name = payload.project.get("name")
    last_commit = payload.object_attributes.get("last_commit") 

    existing_name = doctype_check(project_name)

    if existing_name:
        doc = frappe.get_doc("Deploy Note", existing_name)
        doc.append("merged", {
            "merge_name": last_commit.get("message"),
            "commits": json.dumps(last_commit, indent=2, ensure_ascii=False),
        })
        doc.save(ignore_permissions=True)
        frappe.db.commit()
    else:
        doc = frappe.new_doc("Deploy Note")
        doc.project_name = project_name
        doc.workflow_state = "Not Deploy"
        doc.append("merged", {
            "merge_name": last_commit.get("message"),
            "commits": json.dumps(last_commit, indent=2, ensure_ascii=False),
        })

        doc.flags.ignore_version = True
        doc.save(ignore_permissions=True)
        frappe.db.commit()

    return {
            "success": True
        }

def doctype_check(project_name):
    results = frappe.get_all(
        "Deploy Note",
        filters={
            "project_name": project_name,
            "workflow_state": "Not Deploy",
        },
        fields=["name", "creation"],
        order_by="creation desc",
        limit=1,
    )

    return results[0].name if results else None
    

@frappe.whitelist()
def deploy_to_dev(name, password):
    check_password(frappe.session.user, password)

    run_deploy_dev()

    deploy = frappe.get_doc("Deploy Note", name)
    deploy.workflow_state = "Deploy to Dev"
    deploy.is_deploy_dev = 1
    deploy.save()

    return {
        "success": True
    }

def check_password(user, pwd):
    result = (
		frappe.qb.from_(Auth)
		.select(Auth.name, Auth.password)
		.where(
			(Auth.doctype == "User")
			& (Auth.name == user)
			& (Auth.fieldname == "Password")
			& (Auth.encrypted == 0)
		)
		.limit(1)
		.run(as_dict=True)
	)

    if not result or not passlibctx.verify(pwd, result[0].password):
        raise frappe.throw(_("Incorrect User or Password"))
