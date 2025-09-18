/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Dialog } from "@web/core/dialog/dialog";

function showConfirmDialog(action, options, env) {
    const params = action.params;
    const dialog = new Dialog(null, {
        title: params.title || "Xác nhận",
        size: "medium",
        body: params.message || "Bạn có chắc chắn không?",
        buttons: [
            { text: "Xác nhận", classes: "btn-primary", close: true, click: () => {
                // Gọi phương thức được truyền từ Python và sử dụng model từ params
                env.services.rpc({
                    model: params.model,  // Lấy model từ Python
                    method: params.method,  // Gọi hàm xác nhận trên model này
                    args: [[env.model.data.id]],  // Gửi ID của bản ghi hiện tại
                }).then(() => {
                    window.location.reload();  // Tải lại trang sau khi xác nhận
                });
            }},
            { text: "Hủy", close: true }
        ]
    });
    
    dialog.open();
}

// Đăng ký hành động cho tag 'show_confirm_dialog'
registry.category("actions").add("show_confirm_dialog", showConfirmDialog);
