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
import { useService, useBus, useHistory } from "@web/core/utils/hooks";
import { loadJS } from "@web/core/assets";
import * as BarcodeScanner from "@web/webclient/barcode/barcode_scanner";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { ManualBarcodeScanner } from "@smartbiz_barcode/Components/manual_barcode";
import { url } from "@web/core/utils/urls";
import { utils as uiUtils } from "@web/core/ui/ui_service";
import { DialogModal } from "../dialog/dialogModal";

export class HrInterface extends Component {
  static template = "smartbiz_hr_interface";
  static props = {
    action: { type: Object, optional: true },
    actionId: { type: Number, optional: true },
    className: { type: String, optional: true },
    globalState: { type: Object, optional: true }, // <-- thêm dòng này
  };
  static components = {
    DialogModal,
  };

  setup() {
    this.state = useState({ 
        sidebarVisible: false,
        view: "attendance", // Default view
        search: "",
        img : "",
        employee: "",
        employee_id: null,
        employee_name: "",
        employee_email: null,
        attendance_data: [],
        leave_data: [],
        overtime_data: [],
        payslip_data: [],
        attendanceSummary: { totalCheckinsToday: 0, currentlyCheckedIn: 0, notCheckedOut: 0 },
        leaveSummary: { totalLeaveRequests: 0, pendingLeaveRequests: 0, approvedLeaveRequests: 0 },
        overtimeSummary: { totalOvertimeRequests: 0, pendingOvertimeRequests: 0, approvedOvertimeHours: 0 },
        salarySummary: { totalPaidSalary: 0, averageSalary: 0, totalPayslips: 0 },
        //Các biến Dialog
        showDialogModal: false,
        dialogTitle: "",
        dialogAction:"",
        dialogRecords: [],
        dialogFields:[],
        dialogDefault: null,
        pdf: null,
        showPDF: false,
        selectedPayslip: null,
        selectedLeave: null,
        selectedOvertime: null,

    });
    this.rpc = useService("rpc");
    this.orm = useService("orm");
    this.notification = useService("notification");
    this.dialog = useService("dialog");
    this.action = useService("action");
    this.home = useService("home_menu");
    this.store = useService("mail.store");
    this.userService = useService("user");
    // Refs
    this.sidebarRef = useRef("sidebar");
    this.headerRef = useRef("header");
    this.mainRef = useRef("main");
    this.themeButtonRef = useRef("themeButton");
    this.sidebarLinksRef = useRef("sidebarLinks");

    onMounted(() => {
      const themeBtn = this.themeButtonRef.el;
      const sidebarLinks = this.sidebarLinksRef.el?.querySelectorAll("a");

      // ====== Theme Toggle ======
      const darkTheme = "dark-theme";
      const iconThemeSun = "fa-sun-o"; // Class cho icon mặt trời
      const iconThemeMoon = "fa-moon-o"; // Class cho icon mặt trăng
      const selectedTheme = localStorage.getItem("selected-theme");
      const selectedIcon = localStorage.getItem("selected-icon");

      const getCurrentTheme = () =>
        document.body.classList.contains(darkTheme) ? "dark" : "light";
      const getCurrentIcon = () =>
        themeBtn?.classList.contains(iconThemeMoon)
          ? iconThemeMoon
          : iconThemeSun;

      if (selectedTheme) {
        document.body.classList[selectedTheme === "dark" ? "add" : "remove"](
          darkTheme
        );
        themeBtn?.classList[selectedIcon === iconThemeMoon ? "add" : "remove"](
          iconThemeMoon
        ); // Thêm hoặc bỏ icon mặt trăng
        themeBtn?.classList[selectedIcon === iconThemeSun ? "add" : "remove"](
          iconThemeSun
        ); // Thêm hoặc bỏ icon mặt trời
      }

      themeBtn?.addEventListener("click", () => {
        document.body.classList.toggle(darkTheme);
        themeBtn.classList.toggle(iconThemeSun); // Toggle icon mặt trời
        themeBtn.classList.toggle(iconThemeMoon); // Toggle icon mặt trăng
        localStorage.setItem("selected-theme", getCurrentTheme());
        localStorage.setItem("selected-icon", getCurrentIcon());
      });

      // ====== Sidebar link active state ======
      sidebarLinks?.forEach((link) => {
        link.addEventListener("click", function () {
          sidebarLinks.forEach((l) => l.classList.remove("active-link"));
          this.classList.add("active-link");
        });
      });

      // ====== Hiện sidebar nếu màn hình >= 1150px ======
      // if (window.innerWidth >= 1150) {
      //   this.state.sidebarVisible = true;
      // }
    });

    onWillStart(async () => {
      await this.getData(5);
    });
  }

  updateSummaries() {
        // Attendance Summary
        let totalCheckinsToday = 0;
        let currentlyCheckedIn = 0;
        let notCheckedOut = 0;
        const today = new Date().toISOString().slice(0, 10);

        this.state.attendance_data.forEach(record => {
            if (record.check_in && record.check_in.startsWith(today)) {
                totalCheckinsToday++;
                // Assuming 'false' means not checked out, adjust if Odoo sends a different value for null/false
                if (record.check_out === false || record.check_out === null) {
                    currentlyCheckedIn++;
                    notCheckedOut++;
                }
            }
        });
        this.state.attendanceSummary = { totalCheckinsToday, currentlyCheckedIn, notCheckedOut };

        // Leave Summary
        let totalLeaveRequests = this.state.leave_data.length;
        let pendingLeaveRequests = this.state.leave_data.filter(record => record.state === 'draft').length;
        let approvedLeaveRequests = this.state.leave_data.filter(record => record.state === 'validate').length;
        this.state.leaveSummary = { totalLeaveRequests, pendingLeaveRequests, approvedLeaveRequests };

        // Overtime Summary
        let totalOvertimeRequests = this.state.overtime_data.length;
        let pendingOvertimeRequests = this.state.overtime_data.filter(record => record.state === 'draft').length;
        let approvedOvertimeHours = this.state.overtime_data.filter(record => record.state === 'approved').reduce((sum, record) => sum + record.duration, 0);
        this.state.overtimeSummary = { totalOvertimeRequests, pendingOvertimeRequests, approvedOvertimeHours };

        // Salary Summary - Now uses payslip_data
        let totalPaidSalary = this.state.payslip_data.filter(record => record.state === 'done').reduce((sum, record) => sum + record.net_wage, 0);
        let averageSalary = this.state.payslip_data.length > 0 ? totalPaidSalary / this.state.payslip_data.length : 0;
        let totalPayslips = this.state.payslip_data.length;
        this.state.salarySummary = { totalPaidSalary: totalPaidSalary.toFixed(0), averageSalary: averageSalary.toFixed(0), totalPayslips };
    }

    formatCurrency(value) {
        if (typeof value !== 'number') return value; // Return as is if not a number
        // Use Intl.NumberFormat for Vietnamese currency format (VND)
        return new Intl.NumberFormat('vi-VN', { style: 'currency', currency: 'VND' }).format(value);
    }
    formatDateTime(dateTimeString) {
    if (!dateTimeString) return 'N/A';

    const date = new Date(dateTimeString);

    // Tính lại thời gian theo UTC+7
    const utc7Date = new Date(date.getTime() + 7 * 60 * 60 * 1000);

    return utc7Date.toLocaleString('vi-VN', {
        year: 'numeric',
        month: 'numeric',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
        hour12: false,
        timeZone: 'Asia/Ho_Chi_Minh'  // ép timeZone là UTC nhưng đã cộng offset rồi
    });
}

    // Helper function to determine status badge classes
    getStatusBadgeClass(status) {
        switch (status) {
            case 'validate':
                return 'bg-blue-100 text-blue-800';
            case 'approved':
                return 'bg-green-100 text-green-800';
            case 'to_approve': 
                return 'bg-orange-100 text-orange-800';
            case 'draft':
                return 'bg-yellow-100 text-yellow-800';
            case 'refused':
                return 'bg-red-100 text-red-800';
            case 'status-checked-in':
                return 'bg-green-100 text-green-800';
            case 'status-not-checked-out': 
                return 'bg-orange-100 text-orange-800';
            default:
                return 'bg-gray-100 text-gray-800';
        }
    }

    switchView(viewName) {
        this.state.view = viewName;
        // In Owl, t-if handles visibility, no need for manual class toggling here.
        // Just ensure the state.view is updated.
    }

    onNewEntryClick() {
        alert('Chức năng "Mới" sẽ được thêm vào đây!');
    }
  toggleSidebar() {
    this.state.sidebarVisible = !this.state.sidebarVisible;
  }
  roundToTwo(num) {
    if (isNaN(num)) return 0;
    return Math.round((num + Number.EPSILON) * 100) / 100;
}
  changeTab(tabName) {
    this.state.view = tabName;
    console.log(tabName)
  }
  onSearchChange(event) {
    this.state.search = event.target.value;
    console.log(this.state.search);
    this.search();
  }

  search() {
    if (this.state.search !== "") {
      if(this.state.view === "attendance") {
        console.log("từ từ")
        
      }
    } else {
      console.log("từ từ")
    }
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
    // =====================
  // hàm showModal universal
  // =====================
showModal(title, action = '', defaultValues = null) {
    const formMap = {
        attendance_data: [
            { name: 'employee_name', label: 'Employee', type: 'text', readonly: true },
            { name: 'check_in', label: 'Check In', type: 'datetime-local', required: true },
            { name: 'check_out', label: 'Check Out', type: 'datetime-local' },
            // { name: 'worked_hours', label: 'Worked Hours', type: 'number', readonly: true },
            // { name: 'overtime_hours', label: 'Overtime Hours', type: 'number', readonly: true },
            { name: 'note', label: 'Note', type: 'textarea' },
        ],
        leave_data: [
            { name: 'employee_name', label: 'Employee', type: 'text', readonly: true },
            { name: 'holiday_status_id', label: 'Leave Type', type: 'select', options: this.leaveTypes, required: true },
            { name: 'date_from', label: 'From Date', type: 'date', required: true },
            { name: 'date_to', label: 'To Date', type: 'date', required: true },
            { name: 'number_of_days', label: 'Number of Days', type: 'number', readonly: true },
            // { name: 'state', label: 'Status', type: 'text', readonly: true },
            { name: 'note', label: 'Note', type: 'textarea' },
        ],
        overtime_data: [
            { name: 'employee_name', label: 'Employee', type: 'text', readonly: true },
            { name: 'name', label: 'Request Name', type: 'text', required: true },
            { name: 'start_date', label: 'Start Date', type: 'datetime-local', required: true },
            { name: 'end_date', label: 'End Date', type: 'datetime-local', required: true },
            { name: 'duration', label: 'Duration (hours)', type: 'number', readonly: true },
            // { name: 'state', label: 'Status', type: 'text', readonly: true },
            { name: 'note', label: 'Note', type: 'textarea' },
        ],
        payslip_data: [
            { name: 'employee_name', label: 'Employee', type: 'text', readonly: true },
            { name: 'date_from', label: 'From Date', type: 'datetime-local', required: true },
            { name: 'date_to', label: 'To Date', type: 'datetime-local', required: true },
            { name: 'net_wage', label: 'Net Salary', type: 'number', readonly: true },
            // { name: 'state', label: 'Status', type: 'text', readonly: true },
            { name: 'note', label: 'Note', type: 'textarea' },
        ],
    };

    this.state.dialogTitle   = title;
    this.state.dialogAction  = action;
    this.state.dialogFields  = formMap[action] || [];
    this.state.dialogRecords = []; // form mode
    this.state.dialogDefault = defaultValues;

    this.state.showDialogModal = true;
}


  // ---------------
  // closeModal giữ logic
  closeModal(title,data,action=''){
    if (action === 'attendance_data' && data){
        this.state.selectedActivity = data.id;
        console.log(data)
    }
    if (action === 'leave_data' && data){
        this.state.selectedLeave = data.id;
        console.log(data)
    }
    if (action === 'overtime_data' && data){
        this.state.selectedOvertime = data.id;
        console.log(data)
    }
    if (action === 'payslip_data' && data){
        this.state.selectedPayslip = data.id;
        console.log(data)
    }
    
    // reset
    this.state.showDialogModal=false;
    this.state.dialogTitle='';
    this.state.dialogAction='';
    this.state.dialogFields=[];
    this.state.dialogRecords=[];
    
  }

  viewPDF(id) {
    this.state.showPDF = true
    const pdfUrl = `/web/content?model=hr.payslip&field=salary_attachment_ids&id=${id.id}`;
    console.log(id, pdfUrl)
    this.state.pdf = {
      type: "pdf",
      url: `/web/static/lib/pdfjs/web/viewer.html?file=${encodeURIComponent(
        pdfUrl
      )}`,
    };
    // this.state.view = "ActionDetail";
  }
  closePDF() {
    this.state.showPDF = false
    this.state.pdf = null;
  }
  async getData(id) {
    const data = await this.orm.call(
      "smartbiz.hr.interface",
      "getData",
      [,id]
    );

    console.log(data)
    this.leaveTypes = await this.orm.searchRead(
          'hr.leave.type', [['active', '=', true]], ['id', 'name', 'display_name', 'leave_validation_type']
      );
      console.log(this.leaveTypes)
    this.state.attendance_data = data.attendance_data || [];
    this.state.leave_data = data.leave_data || [];
    this.state.overtime_data = data.overtime_data || [];
    this.state.payslip_data = data.payslip_data || [];
    this.updateSummaries(); // Update summary data after loading
    this.switchView(this.state.view); // Render initial vie

  }
  logout() {
        this.state.img = "";
        this.state.employee = null,
        this.state.employee_name = "";
        this.state.employee_email = null;
  }
  async processBarcode(barcode) {
    var barcodeData = await this.orm.call(
      "smartbiz.hr.interface",
      "get_barcode_data",
      [,barcode]
    );
    // console.log(barcodeData)
    if (!barcodeData || !barcodeData.record) {
      const message = _t("Employee not found or invalid barcode.");
      this.notification.add(message, { type: "warning" });
      return;
      
    }
    if(barcodeData){
      const message = _t(`Đăng nhập thành công ${barcodeData.record.name}!`);
      this.notification.add(message, { type: "success" });
      this.state.img = barcodeData.record.image_1920;
      this.state.employee = barcodeData.record.barcode;
      this.state.employee_id = barcodeData.record.id;
      this.state.employee_name = barcodeData.record.name;
      this.state.employee_email = barcodeData.record.work_email;
      this.getData(barcodeData.record.id);
    }
    

  }
  onViewSalaryDetails(record) {
    // Here you can implement the logic to:
    this.notification.add(_t(`Xem chi tiết bảng lương: ${record.name} (Net: ${this.formatCurrency(record.net_wage)})`), {
        type: "info",
        sticky: true, // Keep the notification visible until user closes it
    });
    console.log("Viewing salary details for:", record);
  }

}

registry.category("actions").add("smartbiz_hr_interface", HrInterface);
