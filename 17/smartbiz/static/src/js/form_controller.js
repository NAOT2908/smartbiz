/** @odoo-module **/

import { FormController } from '@web/views/form/form_controller';
import { patch } from '@web/core/utils/patch';
import { onMounted, onPatched } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { pick } from "@web/core/utils/objects";

import { Component, useState, xml } from "@odoo/owl";

patch(FormController.prototype, {
    setup() {
        super.setup(...arguments);
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.dialogService = useService('dialog');

        this._updateButtonsVisibility = this._updateButtonsVisibility.bind(this);

        onMounted(() => {         
            this._updateButtonsVisibility();           
        });
        onPatched(() => {            
            this._updateButtonsVisibility(); 
        });
    },

    _updateButtonsVisibility() {
        const record = this.model.root.data;
        let buttonsInfo;
        if (record && record.button_permissions) {
            buttonsInfo = JSON.parse(record.button_permissions);
        }

        if (buttonsInfo) {
            this._manageButtonsDisplay(buttonsInfo);
        }
    },

    _manageButtonsDisplay(buttonsInfo) {
        const buttonContainer = this.rootRef.el.querySelector('.o_statusbar_buttons');
        if (!buttonContainer) {
            console.warn("Không tìm thấy container cho nút (o_statusbar_buttons). Bỏ qua việc render nút.");
            return;
        }

        // Duyệt và xóa các nút động không còn trong buttonsInfo
        const existingDynamicButtons = Array.from(buttonContainer.querySelectorAll("button[data-dynamic='true']"));
        
        for (const button of existingDynamicButtons) {
            const functionName = button.getAttribute("name");
            if (!buttonsInfo[functionName]) {
                buttonContainer.removeChild(button);
            }
        }

        // Thêm hoặc hiển thị các nút theo buttonsInfo
        for (const [functionName, buttonData] of Object.entries(buttonsInfo)) {
            let button = buttonContainer.querySelector(`button[name="${functionName}"]`);
            if (buttonData?.visible) {
                if (!button) {
                    // Tạo nút HTML nếu chưa tồn tại
                    button = document.createElement("button");
                    button.setAttribute("name", functionName);
                    button.setAttribute("type", "button");
                    button.setAttribute("data-dynamic", "true");
                    button.className = "btn btn-secondary";
                    button.innerHTML = `<span>${buttonData.translated_name}</span>`;
                    
                    // Thêm sự kiện onClick để xử lý hành động
                    button.onclick = () => this._onButtonClick(functionName);
                    
                    // Thêm nút vào buttonContainer
                    buttonContainer.appendChild(button);
                } else {
                    // Hiển thị nút nếu bị ẩn
                    button.style.display = '';
                }
            } else {
                // Ẩn nút nếu cần
                if (button) {
                    button.style.display = 'none';
                }
            }
        }
    },

    async _onButtonClick(functionName) {
        if (functionName === 'action_delegate') {
            // Mở cửa sổ lựa chọn tùy chỉnh
            this.dialogService.add(DelegateDialog, {
                resModel: this.model.root.resModel,
                resId: this.model.root.resId,
            });
        } else {
            const clickParams = { name: functionName, type: "object" };
            this.env.onClickViewButton({
                clickParams: clickParams,
                getResParams: () =>
                    pick(this.model.root, "context", "evalContext", "resModel", "resId", "resIds"),
                beforeExecute: () => {
                    // Logic trước khi thực thi
                },
            });
        }
    },
});
import { _t } from "@web/core/l10n/translation";
import { Dialog } from "@web/core/dialog/dialog";

class DelegateDialog extends Component {
    setup() {
        this.orm = useService('orm');
        this.notification = useService('notification');
        this.state = useState({
            action: 'reject',
            user_id: null,
            reason: '',
            users: [],
            
        });

        this.loadUsers();
    }

    async loadUsers() {
        const users = await this.orm.searchRead('res.users', [], ['id', 'name']);
        this.state.users = users;
    }

    async confirm() {
        if (!this.state.reason) {

            const message = _t('Vui lòng cung cấp nguyên nhân.');
            this.notification.add(message, { type: "warning" });
            return;
        }
        if (this.state.action === 'transfer' && !this.state.user_id) {
            const message = _t('Vui lòng chọn người dùng để điều chuyển.');
            this.notification.add(message, { type: "warning" });
            return;
        }
        // Gọi phương thức action_delegate
        await this.orm.call(
            this.props.resModel,
            'action_delegate',
            [[this.props.resId], this.state.action, this.state.user_id, this.state.reason]
        );
        this.props.close();  // Đóng dialog
        // Reload form view
        
    }

    cancel() {
        this.props.close();
    }
}

DelegateDialog.template = xml`
        <Dialog title="'Thực hiện ủy quyền'" size="'sm'" fullscreen="false">
            <div class="modal-body">
                <div class="form-group">
                    <label>Hành động:</label>
                    <select t-model="state.action" class="form-control">
                        <option value="reject">Từ chối</option>
                        <option value="transfer">Điều chuyển</option>
                    </select>
                </div>
                <div t-if="state.action === 'transfer'" class="form-group">
                    <label>Người dùng:</label>
                    <select t-model="state.user_id" class="form-control">
                        <option t-att-value="false">-- Chọn người dùng --</option>
                        <t t-foreach="state.users" t-as="user" t-key="user.id">
                            <option t-att-value="user.id"><t t-esc="user.name"/></option>
                        </t>
                    </select>
                </div>
                <div class="form-group">
                    <label>Nguyên nhân:</label>
                    <textarea t-model="state.reason" class="form-control"/>
                </div>
            </div>
            <t t-set-slot="footer">
                <button type="button" class="btn btn-secondary" t-on-click="cancel">Hủy</button>
                <button type="button" class="btn btn-primary" t-on-click="confirm">Xác nhận</button>
            </t>
        </Dialog>
`;
DelegateDialog.components = { Dialog };
DelegateDialog.props = {
    resModel: String,
    resId: Number,
    close: Function,
};

export { DelegateDialog };
