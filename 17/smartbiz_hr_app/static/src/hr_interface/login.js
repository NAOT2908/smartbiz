/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { COMMANDS } from "@barcodes/barcode_handlers";
import { registry } from "@web/core/registry";

import {
  Component,
  EventBus,
  onPatched,
  onWillStart,
  useState,
  useSubEnv,
  xml,
  useEnv,
  onWillUnmount,
  onMounted,
  useRef,
} from "@odoo/owl";
import { HrInterface } from "./hr";
import * as BarcodeScanner from "@web/webclient/barcode/barcode_scanner";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { ManualBarcodeScanner } from "@smartbiz_barcode/Components/manual_barcode";
import { useService, useBus, useHistory } from "@web/core/utils/hooks";

export class LoginComponent extends Component {
    // Định nghĩa mẫu XML cho component
    static template = "LoginComponent";

    // Định nghĩa các thuộc tính mặc định cho component (nếu có)
    static props = {
        action: { type: Object, optional: true },
        actionId: { type: Number, optional: true },
        className: { type: String, optional: true },
        globalState: { type: Object, optional: true }, // <-- thêm dòng này
    };
    static components = { HrInterface }

    /**
     * Khởi tạo trạng thái ban đầu của component.
     * @property {boolean} showPasswordField - Kiểm soát việc hiển thị trường mật khẩu và nút đăng nhập.
     * @property {string} receiveId - Giá trị của trường ID nhận.
     * @property {string} password - Giá trị của trường mật khẩu.
     * @property {string|null} message - Nội dung thông báo hiển thị cho người dùng.
     * @property {string|null} messageType - Loại thông báo ('error', 'success', 'info') để định kiểu.
     */
    setup() {
        this.state = owl.useState({
            showPasswordField: false,
            receiveId: '',
            password: '123456',
            message: null,
            messageType: null,
            img : "",
            employee: "433bcbed",
            employee_id: 5,
            employee_name: "Nguyễn Đức Toàn",
            employee_email: null,
            view: "hr_interface",
        });
        this.rpc = useService("rpc");
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.dialog = useService("dialog");
        this.action = useService("action");
        this.home = useService("home_menu");
        this.store = useService("mail.store");
        this.userService = useService("user");
        this.barcodeService = useService("barcode");
        useBus(this.barcodeService.bus, "barcode_scanned", (ev) =>
        this.onBarcodeScanned(ev.detail.barcode)
        );
    }

    async onReceiveIdKeyup(ev) {
        // console.log(ev.target.value);
        const value = ev.target.value.trim();
        if (value) {
            // console.log(value)
            const employees = await this.orm.searchRead(
            'hr.employee', [['barcode', '=', value]], ['id', 'name', 'display_name', 'pin', 'image_1920', 'barcode']
            );
            // console.log(id)
            if (employees.length === 0) {
                const message = _t("Barcode not found. Please scan or enter the correct barcode.");
                this.notification.add(message, { type: "danger" });
                
                return;
            }
            this.state.employee_id = employees[0].id;
            this.state.employee_name = employees[0].name;
            this.state.img = employees[0].image_1920;
            this.state.employee_email = employees[0].work_email;
            this.state.employee = employees[0].barcode;
            
        }
    }
    onKeydown(ev) {
        if (ev.key === "Enter") {
            this.onLoginClick();
        }
    }
    async onLoginClick() {
        const password = this.state.password.trim();
        if (!password) {
            const message = _t("Please enter your password.");
            this.notification.add(message, { type: "danger" });
            return;
        }
        
        const pin = await this.orm.searchRead(
          'hr.employee', [['id', '=', this.state.employee_id]], ['id', 'name', 'barcode', 'display_name', 'pin']
        );
        console.log(pin)
        if(password === pin[0].pin) {  
            this.state.view = "hr_interface";
            this.state.img = pin[0].image_1920;
            this.state.employee = pin[0].barcode;
            this.state.employee_id = pin[0].id;
            this.state.employee_name = pin[0].name;
            this.state.employee_email = pin[0].work_email;
            this.notification.add(_t("Login successful!"), { type: "success" });
        }
        else {
            this.state.view = "login";
            const message = _t("Invalid password. Please try again.");
            this.notification.add(message, { type: "danger" });
        }
    }

    logOut() {
        if (!this.state.view) {
        console.error("State is undefined in logOut");
        return;
    }
        this.state.view = "login";
        this.state.img = "";
        this.state.employee = "";
        this.state.employee_id = null;
        this.state.employee_name = "";
        this.state.employee_email = null;
        this.notification.add(_t("Logout successful!"), { type: "success" });
    }
    async openMobileScanner() {
        const barcode = await BarcodeScanner.scanBarcode(this.env);
        await this.onBarcodeScanned(barcode);
    }

  openManualScanner() {
    this.dialog.add(ManualBarcodeScanner, {
      openMobileScanner: async () => {
        await this.openMobileScanner();
      },
      onApply: async (barcode) => {
        await this.onBarcodeScanned(barcode);
      },
    });
  }
  async onBarcodeScanned(barcode) {
    if (barcode) {
      await this.processBarcode(barcode, this.picking_id);

      if ("vibrate" in window.navigator) {
        window.navigator.vibrate(100);
      }
    } else {
      const message = _t("Please, Scan again!");
      this.notification.add(message, { type: "warning" });
    }
  }
  async processBarcode(barcode) {
    var barcodeData = await this.orm.call(
      "smartbiz.hr.interface",
      "get_barcode_data",
      [,barcode]
    );
    console.log(barcodeData)
    if (!barcodeData || !barcodeData.record) {
      const message = _t("Employee not found or invalid barcode.");
      this.notification.add(message, { type: "warning" });
      return;
      
    }
    if(barcodeData){
      this.state.img = barcodeData.record.image_1920;
      this.state.employee = barcodeData.record.barcode;
      this.state.employee_id = barcodeData.record.id;
      this.state.employee_name = barcodeData.record.name;
      this.state.employee_email = barcodeData.record.work_email;
      const message = _t(`Nhân viên ${barcodeData.record.name}!`);
      this.notification.add(message, { type: "success" });
    }

  }
}

registry.category("actions").add("smartbiz_hr_interface", LoginComponent);
