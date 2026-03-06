import frappe
import json
import subprocess
from frappe import _
from frappe.query_builder import Table
from passlib.context import CryptContext

import os
import glob

import shutil

def get_bench_executable():
    import os

    # Prioritas 1: dari site_config
    from_config = frappe.conf.get("bench_executable")
    if from_config and os.path.exists(from_config):
        return from_config

    # Prioritas 2: common paths
    bench_path = frappe.utils.get_bench_path()
    candidates = [
        "/home/fikri/.local/bin/bench",
        "/home/frappe/.local/bin/bench",
        f"{bench_path}/env/bin/bench",
        "/usr/local/bin/bench",
    ]
    for p in candidates:
        if os.path.exists(p):
            return p

    raise Exception(f"bench executable tidak ditemukan! Set 'bench_executable' di site_config.json")


def run_command(cmd, cwd=None):
    import os
    import glob

    bench_path = frappe.utils.get_bench_path()
    home_dir = os.path.expanduser("~")

    # Cari node path otomatis (nvm atau system)
    node_path = ""
    nvm_versions = glob.glob(f"{home_dir}/.nvm/versions/node/*/bin")
    if nvm_versions:
        # Ambil versi terbaru
        nvm_versions.sort(reverse=True)
        node_path = nvm_versions[0]

    env = os.environ.copy()
    env["HOME"] = home_dir
    env["PATH"] = ":".join(filter(None, [
        f"{bench_path}/env/bin",
        node_path,
        "/usr/local/bin",
        "/usr/bin",
        "/bin",
        env.get("PATH", "")
    ]))
    env["GIT_SSH_COMMAND"] = f"ssh -i {home_dir}/.ssh/id_rsa -o StrictHostKeyChecking=no -o BatchMode=yes"

    result = subprocess.run(
        cmd,
        shell=True,
        cwd=cwd,
        capture_output=True,
        text=True,
        env=env
    )

    if result.returncode != 0:
        raise Exception(result.stderr or result.stdout)

    return result.stdout
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


def get_latest_backup(site):
    backup_path = f"./sites/{site}/private/backups"
    files = glob.glob(f"{backup_path}/*database.sql.gz")
    files.sort(reverse=True)

    return files[0] if files else None


def run_deploy_dev():
    bench_path = frappe.utils.get_bench_path()
    site_name = frappe.local.site
    app_path = f"{bench_path}/apps/sokka_core_customization"
    bench_bin = get_bench_executable()
    log_lines = []
    backup_file = None

    try:
        # ✅ tambah --site
        out = run_command(f"{bench_bin} --site {site_name} backup", cwd=bench_path)
        log_lines.append(f"[backup]\n{out}")

        backup_file = get_latest_backup(site_name)
        log_lines.append(f"[backup file] {backup_file}")

        out = run_command("git checkout develop", cwd=app_path)
        log_lines.append(f"[git checkout]\n{out}")

        out = run_command("git pull upstream develop", cwd=app_path)
        log_lines.append(f"[git pull]\n{out}")

        # ✅ sudah ada --site
        out = run_command(f"{bench_bin} --site {site_name} migrate", cwd=bench_path)
        log_lines.append(f"[migrate]\n{out}")

        lock_file = f"{bench_path}/config/bench_build.lock"
        if os.path.exists(lock_file):
            os.remove(lock_file)
            frappe.logger().info("[deploy] Removed stale bench_build.lock")

        out = run_command(f"{bench_bin} build", cwd=bench_path)
        log_lines.append(f"[build]\n{out}")
        
        out = run_command(f"{bench_bin} build", cwd=bench_path)
        log_lines.append(f"[build]\n{out}")


        # ⚠️ bench restart mungkin butuh sudo — kita skip dulu, test sampai sini
        out = run_command(f"{bench_bin} restart", cwd=bench_path)
        log_lines.append(f"[restart]\n{out}")

        return {"success": True, "log": "\n\n".join(log_lines)}

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Deploy Dev Failed")
        log_lines.append(f"[ERROR]\n{str(e)}")

        if backup_file:
            try:
                log_lines.append("[rollback] Memulai rollback...")
                run_command(f"{bench_bin} --site {site_name} restore {backup_file}", cwd=bench_path)
                run_command(f"{bench_bin} --site {site_name} migrate", cwd=bench_path)
                run_command(f"{bench_bin} restart", cwd=bench_path)
                log_lines.append("[rollback] Rollback berhasil.")
            except Exception as rollback_err:
                log_lines.append(f"[rollback ERROR] {str(rollback_err)}")

        frappe.throw(f"Deploy gagal dan sudah di-rollback.\n\n{str(e)}")