// Copyright (c) 2026, Sokka Kreatif Teknologi and contributors
// For license information, please see license.txt

frappe.ui.form.on("Deploy Note", {
	refresh(frm) {},

	deploy(frm) {
		let d = new frappe.ui.Dialog({
			title: "Deploy to Dev",
			fields: [
				{
					label: "Password",
					fieldname: "password",
					fieldtype: "Password",
					reqd: 1,
				},
			],
			primary_action_label: "Deploy",
			primary_action(values) {
				d.hide();
				deploy_to_dev(frm, values.password);
			},
		});
		d.show();
	},
});

function deploy_to_dev(frm, password) {
	// Tampilkan loading dialog
	let loading = new frappe.ui.Dialog({
		title: "⏳ Deploying...",
		fields: [
			{
				fieldtype: "HTML",
				fieldname: "loading_html",
				options: `
                    <div style="text-align: center; padding: 20px;">
                        <div class="loading-indicator" style="margin-bottom: 16px;">
                            <svg width="48" height="48" viewBox="0 0 50 50" style="animation: rotate 1s linear infinite;">
                                <circle cx="25" cy="25" r="20" fill="none" stroke="#5e64ff" stroke-width="4"
                                    stroke-dasharray="80 20" stroke-linecap="round"/>
                            </svg>
                        </div>
                        <p style="font-size: 15px; color: #555; margin: 0;">
                            Sedang menjalankan deploy...<br>
                            <small style="color: #888;">Mohon jangan tutup halaman ini</small>
                        </p>
                    </div>
                    <style>
                        @keyframes rotate {
                            100% { transform: rotate(360deg); }
                        }
                    </style>
                `,
			},
		],
	});

	// Sembunyikan tombol close & cancel
	loading.show();
	loading.$wrapper.find(".modal-header .btn-modal-close").hide();
	loading.get_close_btn().hide();

	frappe.call({
		method: "skt_deploy.controller.api.webhook.deploy_to_dev",
		args: {
			name: frm.doc.name,
			password: password,
		},
		callback(res) {
			loading.hide();

			if (res.message?.success) {
				frappe.show_alert({ message: "✅ Deploy berhasil!", indicator: "green" }, 5);
				frm.reload_doc();
			}
		},
		error(err) {
			loading.hide();

			let error_msg = err?.message || "Terjadi kesalahan saat deploy.";
			frappe.msgprint({
				title: "❌ Deploy Gagal",
				message: error_msg,
				indicator: "red",
			});
			frm.reload_doc();
		},
	});
}
