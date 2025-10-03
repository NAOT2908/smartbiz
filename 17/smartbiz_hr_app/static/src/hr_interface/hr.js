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
const { DateTime } = luxon;
import { formatDate, formatDateTime } from "@web/core/l10n/dates";
import { parseDateTime, parseDate } from "@web/core/l10n/dates";

// A simple utility function for date formatting
function formatDisplayDate(date) {
  const d = new Date(date);
  const day = d.getDate();
  const month = d.getMonth() + 1;
  const year = d.getFullYear();
  return `${day} tháng ${month} ${year}`;
}

function formatDateToUTC(date) {
  // Trả về chuỗi dạng 'YYYY-MM-DD HH:mm:ss'
  return date.toISOString().slice(0, 19).replace("T", " ");
}

export class HrInterface extends Component {
  static template = "smartbiz_hr_interface";
  static props = {
    action: { type: Object, optional: true },
    actionId: { type: Number, optional: true },
    className: { type: String, optional: true },
    globalState: { type: Object, optional: true },
    employee_id: { type: Number, optional: true },
    logOut: { type: Function, optional: true },
    employee: { type: String, optional: true },
    employee_name: { type: String, optional: true },
  };
  static components = {
    DialogModal,
  };

  setup() {
    this.state = useState({
      sidebarVisible: false,
      view: "home", 
      search: "",
      img: "",
      data: [],
      employee: this.props.employee || "",
      employee_id: this.props.employee_id || null,
      employee_name: this.props.employee_name || null,
      employee_email: null,
      attendance_data: [],
      leave_data: [],
      overtime_data: [],
      payslip_data: [],
      workentry_data: [],
      attendanceSummary: {
        totalCheckinsToday: 0,
        currentlyCheckedIn: 0,
        notCheckedOut: 0,
      },
      leaveSummary: {
        totalLeaveRequests: 0,
        pendingLeaveRequests: 0,
        approvedLeaveRequests: 0,
      },
      overtimeSummary: {
        totalOvertimeRequests: 0,
        pendingOvertimeRequests: 0,
        approvedOvertimeHours: 0,
      },
      salarySummary: { totalPaidSalary: 0, averageSalary: 0, totalPayslips: 0 },
      //Các biến Dialog
      showDialogModal: false,
      dialogTitle: "",
      dialogAction: "",
      dialogRecords: [],
      dialogFields: [],
      dialogDefault: null,
      pdf: null,
      showPDF: false,
      showAlert: false,
      selectedPayslip: null,
      selectedLeave: null,
      selectedOvertime: null,
      selectedIds: [],
      allocation_data: [],
      filteredEntries: [],
      workentry_summary: [],
      currentFilterDate: new Date(),
      currentFilterType: "month",
      filterTypeLabel: "Month",
      searchTerm: "",
      modalOpen: false,
      selectedEntry: null,
      isDropdownOpen: false,
      filterType: "month",
      currentDate: new Date(),
      searchTerm: "",
      date_from: null,
      date_to: null,
      alert_data: [],
      selectedAlert: null,
      workEntryTypes: [],
      leaveTypes: [],
      alertTypes: [],
      selectedType: "",
    });

    this.displayMode = useState({ mode: "list" });
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
    this.isMobile = uiUtils.isSmall();
    this.barcodeService = useService("barcode");
    useBus(this.barcodeService.bus, "barcode_scanned", (ev) =>
      this.onBarcodeScanned(ev.detail.barcode)
    );
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
      // sidebarLinks?.forEach((link) => {
      //   link.addEventListener("click", function () {
      //     sidebarLinks.forEach((l) => l.classList.remove("active-link"));
      //     this.classList.add("active-link");
      //   });
      // });

    });

    // this.filterEntries();

    onWillStart(async () => {
      await this.getData(this.state.employee_id);
    });
  }
  setMode(mode) {
    this.displayMode.mode = mode;
  }
 
  mapStatus(state) {
    return (
      {
        draft: "Nháp",
        confirm: "Cần phê duyệt",
        validate: "Đã phê duyệt",
        validate1: "Đã phê duyệt lần 2",
        refused: "Từ chối",
        refuse : "Từ chối",
        to_submit: "Chờ kiểm tra",
        to_approve: "Chờ phê duyệt",
        approved: "Đã phê duyệt",
        open: "Mở",
        ack: "Đã xác nhận",
        resolved: "Đã giải quyết",
      }[state] || state
    );
  }
    getIconConfig(typeName) {
    const map = {
        "Chuyên cần": { icon: "🗓️", color: "bg-green-100 text-green-800" },
        "Home Working": { icon: "💻", color: "bg-blue-100 text-blue-800" },
        "Nghỉ phép chung": { icon: "🏖️", color: "bg-yellow-100 text-yellow-800" },
        "Nghỉ phép năm": { icon: "🌴", color: "bg-teal-100 text-teal-800" },
        "Ngày nghỉ bù": { icon: "🔄", color: "bg-purple-100 text-purple-800" },
        "Nghỉ bệnh": { icon: "🤒", color: "bg-red-100 text-red-800" },
        "Không thanh toán": { icon: "💸", color: "bg-pink-100 text-pink-800" },
        "Không có hợp đồng": { icon: "❌", color: "bg-gray-200 text-gray-700" },
        "Giờ tăng ca": { icon: "⚡", color: "bg-orange-100 text-orange-800" },
    };
    return map[typeName] || { icon: "📌", color: "bg-gray-100 text-gray-800" };
}


  formatCurrency(value) {
    if (typeof value !== "number") return value; // Return as is if not a number
    // Use Intl.NumberFormat for Vietnamese currency format (VND)
    return new Intl.NumberFormat("vi-VN", {
      style: "currency",
      currency: "VND",
    }).format(value);
  }
  formatDateTime(dateTimeString) {
    if (!dateTimeString) return "N/A";

    const date = new Date(dateTimeString);

    // Tính lại thời gian theo UTC+7
    const utc7Date = new Date(date.getTime() + 7 * 60 * 60 * 1000);

    return utc7Date.toLocaleString("vi-VN", {
      year: "numeric",
      month: "numeric",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
      timeZone: "Asia/Ho_Chi_Minh", // ép timeZone là UTC nhưng đã cộng offset rồi
    });
  }

  // Helper function to determine status badge classes
  getStatusBadgeClass(status) {
    switch (status) {
      case "validate":
        return "px-3 py-1 text-xs font-medium rounded-full bg-green-100 text-green-800";
      case "approved":
      case "resolved":
        return "px-3 py-1 text-xs font-medium rounded-full bg-green-100 text-green-800";
      case "to_submit":
        return "px-3 py-1 text-xs font-medium rounded-full bg-blue-100 text-blue-800";
      case "confirm":
        return "px-3 py-1 text-xs font-medium rounded-full bg-blue-100 text-blue-800";
      case "to_approve":
        return "px-3 py-1 text-xs font-medium rounded-full bg-orange-100 text-orange-800";
      case "draft":
      case "open":
        return "px-3 py-1 text-xs font-medium rounded-full bg-yellow-100 text-yellow-800";
      case "refuse":
        return "px-3 py-1 text-xs font-medium rounded-full bg-red-100 text-red-800";
      case "status-checked-in":
        return "px-3 py-1 text-xs font-medium rounded-full bg-green-100 text-green-800";
      case "ack":
        return "px-3 py-1 text-xs font-medium rounded-full bg-orange-100 text-orange-800";
      default:
        return "px-3 py-1 text-xs font-medium rounded-full bg-gray-100 text-gray-800";
    }
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
  async changeTab(tabName) {
    const { date_from, date_to } = this.getDateRange();
    this.state.view = tabName;
    if(tabName === "workentry"){
      const summary = await this.orm.call("smartbiz.hr.interface", "getWorkentrySummary", [, this.state.employee_id, date_from, date_to]);
      console.log(summary)
      this.state.workentry_summary = summary || [];
    }
    else if (tabName === "attendance") {
      // const summary = await this.orm.call("smartbiz.hr.interface", "getAttendanceSummary", [, this.state.employee_id, date_from, date_to]);
      // this.state.attendanceSummary = summary;
      // console.log(summary);
    } else if (tabName === "leave") {
      const summary = await this.orm.call("smartbiz.hr.interface", "getLeaveSummary", [, this.state.employee_id]);
      this.state.allocation_data = summary || [];
      // console.log(summary)
    } else if (tabName === "alert") {
      const summary = await this.orm.call("smartbiz.hr.interface", "getAttendanceAlert", [, this.state.employee_id, date_from, date_to]);
      this.state.alert_data = summary || [];
      // console.log(summary);
    }
    
  }
  onSearchChange(event) {
    this.state.search = event.target.value;
    // console.log(this.state.search);
    this.search();
  }

  search() {
    if (this.state.search !== "") {
      if (this.state.view === "attendance") {
        console.log("từ từ");
      }
    } else {
      console.log("từ từ");
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

  // Chọn hoặc bỏ chọn 1 record
  toggleSelect(recordId, isChecked) {
    const idx = this.state.selectedIds.indexOf(recordId);
    if (isChecked && idx === -1) {
      this.state.selectedIds.push(recordId);
    } else if (!isChecked && idx !== -1) {
      this.state.selectedIds.splice(idx, 1);
    }
  }

  // Chọn hoặc bỏ chọn tất cả
  toggleSelectAll(isChecked) {
    if (isChecked) {
      this.state.selectedIds = this.state.attendance_data.map((r) => r.id);
    } else {
      this.state.selectedIds = [];
    }
  }

  // Kiểm tra 1 record có đang được chọn không
  isSelected(recordId) {
    return this.state.selectedIds.includes(recordId);
  }

  // Kiểm tra SelectAll checkbox có được chọn không
  isAllSelected() {
    return (
      this.state.selectedIds.length === this.state.attendance_data.length &&
      this.state.attendance_data.length > 0
    );
  }
  // =====================
  // hàm showModal universal
  // =====================
  showModal(title, action = "", defaultValues = null) {
    console.log(defaultValues)
    const timeOptions = Array.from({ length: 48 }, (_, i) => {
      const hour = Math.floor(i / 2);      // 0 -> 23
      const minute = i % 2 === 0 ? 0 : 30; // 0 hoặc 30
      const id = hour + (minute === 30 ? 0.5 : 0);

      // chuyển sang 12h + AM/PM
      const period = hour < 12 ? "AM" : "PM";
      const displayHour = hour % 12 === 0 ? 12 : hour % 12;
      const displayMinute = minute.toString().padStart(2, "0");

      return {
        id: id, // 0, 0.5, 1, 1.5 ... 23.5
        name: `${displayHour}:${displayMinute} ${period}`, // "12:00 AM", "12:30 AM", ...
      };
    });
    const formMap = {
      attendance_data: [
        {
          name: "employee_ids",
          type: "multiselect",
          label: "Employee",
          required: true,
          columns: [
            { key: "name", label: "Employee" },
            { key: "barcode", label: "Code" },
            { key: "department_id", label: "Department" },
          ],
          options: this.employees,
        },
        {
          name: "check_in",
          label: "Check In",
          type: "datetime-local",
          required: true,
        },
        { 
          name: "check_out",
          label: "Check Out", 
          type: "datetime-local" 
        },
        { name: "note", label: "Note", type: "textarea" },
      ],
      leave_data: [
        {
          name: "employee_ids",
          type: "multiselect",
          label: "Employee",
          required: true,
          columns: [
            { key: "name", label: "Employee" },
            { key: "barcode", label: "Code" },
            { key: "department_id", label: "Department" },
          ],
          options: this.employees,
        },
        {
          name: "holiday_status_id",
          label: "Leave Type",
          type: "select",
          options: this.leaveTypes,
          required: true,
        },
        {
          name: "date_from",
          label: "From Date",
          type: "date",
          required: true,
        },
        {
          name: "date_to",
          label: "To Date",
          type: "date",
        },
        {
          name: "request_hour_from",
          label: "From",
          type: "select",
          options: timeOptions
        },
        {
          name: "request_hour_to",
          label: "To",
          type: "select",
          options: timeOptions
        },
        // {
        //   name: "number_of_days",
        //   label: "Number of Days",
        //   type: "number",
        //   readonly: true,
        // },
        { name: 'take_with', label: 'Take with', type: 'text', },
        { name: 'plate_number', label: 'license plate number', type: 'text', },
        { name: "note", label: "Note", type: "textarea" },
      ],
      overtime_data: [
        {
          name: "employee_ids",
          type: "multiselect",
          label: "Employee",
          required: true,
          columns: [
            { key: "name", label: "Employee" },
            { key: "barcode", label: "Code" },
            { key: "department_id", label: "Department" },
          ],
          options: this.employees,
        },
        { name: "name", label: "Request Name", type: "text", required: true },
        {
          name: "start_date",
          label: "Start Date",
          type: "datetime-local",
          required: true,
        },
        {
          name: "end_date",
          label: "End Date",
          type: "datetime-local",
          required: true,
        },
        {
          name: "duration",
          label: "Duration (hours)",
          type: "number",
          readonly: true,
        },
        // { name: 'state', label: 'Status', type: 'text', readonly: true },
        { name: "note", label: "Note", type: "textarea" },
      ],
      alert_data: [
        {
          name: "employee_name",
          label: "Employee",
          type: "text",
          readonly: true,
        },
        {
          name: "block_start",
          label: "Start Time",
          type: "datetime-local",
          readonly: true,
        },
        {
          name: "block_end",
          label: "End Time",
          type: "datetime-local",
          readonly: true,
        },
        {
          name: "net_wage",
          label: "Net Salary",
          type: "number",
          readonly: true,
        },
        // { name: 'state', label: 'Status', type: 'text', readonly: true },
        { name: "note", label: "Note", type: "textarea" },
      ],
    };

    this.state.dialogTitle = title;
    this.state.dialogAction = action;
    this.state.dialogFields = formMap[action] || [];
    this.state.dialogRecords = []; // form mode
    this.state.dialogDefault = defaultValues;

    this.state.showDialogModal = true;
  }

  // ---------------
  // closeModal giữ logic
  async closeModal(title, data, action = "") {
    console.log(title, data, action);
    if (action === "attendance_data" && data) {
      this.state.selectedActivity = data.id;
      // const hr_data = await this.orm.call(
      //   "smartbiz.hr.interface",
      //   "create_attendance",
      //   [, data.employee_ids, data]
      // );
      // await this.getData(this.state.employee_id);
      // console.log(hr_data);
    }
    if (action === "leave_data" && data) {
      this.state.selectedLeave = data.id;
      const hr_data = await this.orm.call(
        "smartbiz.hr.interface",
        "create_leave",
        [, data.employee_ids, data]
      );
      // console.log(data, hr_data);
      await this.getData(this.state.employee_id);
    }
    if (action === "overtime_data" && data) {
      this.state.selectedOvertime = data.id;
      const hr_data = await this.orm.call(
        "smartbiz.hr.interface",
        "create_overtime",
        [, data.employee_ids, data, this.state.employee_id]
      );
     await this.getData(this.state.employee_id);
    }
    if (action === "alert" && data) {
      
    }

    // reset
    this.state.showDialogModal = false;
    this.state.dialogTitle = "";
    this.state.dialogAction = "";
    this.state.dialogFields = [];
    this.state.dialogRecords = [];
  }

  openAlert(record) {
    this.state.showAlert = true;
    this.state.selectedAlert = record.alert_data;
    // console.log(record)
  }

  closeAlert() {
    this.state.showAlert = false;
  }

  async create_attendance_leave(type, record) {
    if (type === "attendance") {
      this.changeTab("attendance");
        // const data = await this.orm.call("smartbiz.hr.interface", "create_alert_attendance", [, this.state.employee_id, record]);
        // await this.getData(this.state.employee_id);
      }
    else if (type === "leave") {
      this.changeTab("leave");
              
    }
    this.state.showAlert = false;
  }

  viewPDF(id) {
    this.state.showPDF = true;
    const pdfUrl = `/web/content?model=hr.payslip&field=salary_attachment_ids&id=${id.id}`;
    console.log(id, pdfUrl);
    this.state.pdf = {
      type: "pdf",
      url: `/web/static/lib/pdfjs/web/viewer.html?file=${encodeURIComponent(
        pdfUrl
      )}`,
    };
    // this.state.view = "ActionDetail";
  }
  closePDF() {
    this.state.showPDF = false;
    this.state.pdf = null;
  }
  async getData(id) {
    const { date_from, date_to } = this.getDateRange();
    // console.log(date_from, date_to);
    const data = await this.orm.call("smartbiz.hr.interface", "getData", [
      ,
      id,
      date_from,
      date_to,
    ]);

    console.log(data);
    this.employees = await this.orm.searchRead(
      "hr.employee",
      [["active", "=", true]],
      ["id", "name", "barcode", "work_email", "pin", "department_id"]
    );
    // console.log(this.employees);
    this.leaveTypes = await this.orm.searchRead(
        "hr.leave.type",
        [
          "|",
            ["requires_allocation", "=", "no"],
            "&",
              ["has_valid_allocation", "=", true],
              "&",
                ["max_leaves", ">", 0],
                "|",
                  ["allows_negative", "=", true],
                  "&",
                    ["virtual_remaining_leaves", ">", 0],
                    ["allows_negative", "=", false],
        ],
        ["id", "name"],
        {
          context: {
            employee_id: id,  
          },
        }
      );
    this.state.workEntryTypes = await this.orm.searchRead(
        "hr.work.entry.type",
        [],
        ["id", "name", "code"]
      );
    // this.aletTypes = await this.orm.searchRead(
    //     "smartbiz_hr.attendance_alert",
    //     [],
    //     ["id", "name"]
    //   );
    // console.log(this.leaveTypes, this.workEntryTypes, this.aletTypes);
    if(this.state.view === "workentry"){
      const summary = await this.orm.call("smartbiz.hr.interface", "getWorkentrySummary", [, this.state.employee_id, date_from, date_to]);
      console.log(summary)
      this.state.workentry_summary = summary || [];
    }
    else if (this.state.view === "attendance") {
      // const summary = await this.orm.call("smartbiz.hr.interface", "getAttendanceSummary", [, this.state.employee_id, date_from, date_to]);
      // this.state.attendanceSummary = summary;
      // console.log(summary);
    } else if (this.state.view === "leave") {
      const summary = await this.orm.call("smartbiz.hr.interface", "getLeaveSummary", [, this.state.employee_id]);
      this.state.allocation_data = summary || [];
      // console.log(summary);
    }else if (this.state.view === "alert") {
      const summary = await this.orm.call("smartbiz.hr.interface", "getAttendanceAlert", [, this.state.employee_id, date_from, date_to]);
      this.state.alert_data = summary || [];
      // console.log(summary);
    }
    this.updateData(data);
    // console.log(this.state.selectedType);
  }

  updateData(data) {
    this.state.data = data || [];
    this.state.attendance_data = data.attendance_data || [];
    this.state.leave_data = data.leave_data || [];
    this.state.overtime_data = data.overtime_data || [];
    this.state.payslip_data = data.payslip_data || [];
    this.state.workentry_data = data.workentry_data || [];
    if (this.state.view === "workentry") {
      if (this.state.selectedType && this.state.selectedType !== "all") {
        this.filterEntries();
      }  
    }
    else if (this.state.view === "leave") {
      if (this.state.selectedType && this.state.selectedType !== "all") {
        this.filterEntries();
      }
    }
    
  }

  logout() {
    this.props.logOut();
  }

  //<--- Lọc ngày  --->
  onChangeType(ev) {
    
      this.state.selectedType = ev.target.value;
      // console.log(this.state.selectedType);
      this.filterEntries();
  }
  filterEntries() {
    if(this.state.view === "workentry") {
      if (this.state.selectedType === "" || this.state.selectedType === "all") {
          // reset về full data
          this.state.workentry_data = this.state.data.workentry_data;
          return;
      }

      const selectedId = parseInt(this.state.selectedType);
      this.state.workentry_data = this.state.data.workentry_data.filter(
          x => x.work_entry_type_id[0] === selectedId
      );
    } else if(this.state.view === "leave") {
      if (this.state.selectedType === "" || this.state.selectedType === "all") {
          
          this.state.leave_data = this.state.data.leave_data;
          return;
      }
      this.state.leave_data = this.state.data.leave_data.filter(
          x => x.holiday_status_id[0] == this.state.selectedType
      );
    }
      
  }
  onSearchInput(ev) {
    this.state.searchTerm = ev.target.value;
    console.log(this.state.searchTerm);
  }

  toggleDropdown() {
    this.state.isDropdownOpen = !this.state.isDropdownOpen;
  }

  prev() {
    this.adjustDate(-1);
  }
  next() {
    this.adjustDate(1);
  }
  today() {
    this.state.currentDate = new Date();
    this.updateRangeDisplay();
    this.getData(this.state.employee_id);
    console.log(this.state.currentDate);
  }
  getDateRange() {
    const { currentDate, filterType } = this.state;
    let start, end;

    switch(filterType){
        case 'day':
            start = DateTime.fromJSDate(currentDate).setZone('Asia/Ho_Chi_Minh').startOf('day');
            end   = DateTime.fromJSDate(currentDate).setZone('Asia/Ho_Chi_Minh').endOf('day');
            break;
        case 'week':
            start = DateTime.fromJSDate(currentDate).setZone('Asia/Ho_Chi_Minh').startOf('week');
            end   = start.plus({ days: 6 }).endOf('day');
            break;
        case 'month':
            start = DateTime.fromJSDate(currentDate).setZone('Asia/Ho_Chi_Minh').startOf('month');
            end   = DateTime.fromJSDate(currentDate).setZone('Asia/Ho_Chi_Minh').endOf('month');
            break;
        case 'year':
            start = DateTime.fromJSDate(currentDate).setZone('Asia/Ho_Chi_Minh').startOf('year');
            end   = DateTime.fromJSDate(currentDate).setZone('Asia/Ho_Chi_Minh').endOf('year');
            break;
    }

    return {
        date_from: start.toFormat("yyyy-MM-dd HH:mm:ss"),
        date_to: end.toFormat("yyyy-MM-dd HH:mm:ss"),
    };
  }

  async setFilter(type, label) {
    // console.log(type, label);
    this.state.filterType = type;
    this.state.filterTypeLabel = label;
    this.state.isDropdownOpen = false;

    this.updateRangeDisplay();
    await this.getData(this.state.employee_id);
  }

  adjustDate(multiplier) {
    let current = DateTime.fromJSDate(this.state.currentDate);

    switch (this.state.filterType) {
      case "day":
        current = current.plus({ days: multiplier });
        break;
      case "week":
        current = current.plus({ weeks: multiplier });
        break;
      case "month":
        current = current.plus({ months: multiplier });
        break;
      case "year":
        current = current.plus({ years: multiplier });
        break;
    }

    this.state.currentDate = current.toJSDate();
    this.updateRangeDisplay();
    this.getData(this.state.employee_id);
    
  }

  updateRangeDisplay() {
    const current = DateTime.fromJSDate(this.state.currentDate);
    let display = "";

    switch (this.state.filterType) {
      case "day":
        display = current.toLocaleString(DateTime.DATE_FULL);
        break;
      case "week": {
        const start = current.startOf("week");
        const end = current.endOf("week");
        display = `${start.toLocaleString(
          DateTime.DATE_FULL
        )} - ${end.toLocaleString(DateTime.DATE_FULL)}`;
        break;
      }
      case "month":
        display = `${current.toFormat("LLLL yyyy")}`; // tháng tên đầy đủ + năm
        break;
      case "year":
        display = `${current.year}`;
        break;
    }

    this.currentRangeDisplay = display;
  }

  //<---- Barcode ----->
  async processBarcode(barcode) {
    var barcodeData = await this.orm.call(
      "smartbiz.hr.interface",
      "get_barcode_data",
      [, barcode]
    );
    // console.log(barcodeData)
    if (!barcodeData || !barcodeData.record) {
      const message = _t("Employee not found or invalid barcode.");
      this.notification.add(message, { type: "warning" });
      return;
    }
    if (barcodeData) {
      this.state.img = barcodeData.record.image_1920;
      this.state.employee = barcodeData.record.barcode;
      this.state.employee_id = barcodeData.record.id;
      this.state.employee_name = barcodeData.record.name;
      this.state.employee_email = barcodeData.record.work_email;
      this.getData(barcodeData.record.id);
      const message = _t(`Đăng nhập thành công ${barcodeData.record.name}!`);
      this.notification.add(message, { type: "success" });
    }
  }
  onViewSalaryDetails(record) {
    // Here you can implement the logic to:
    this.notification.add(
      _t(
        `Xem chi tiết bảng lương: ${record.name} (Net: ${this.formatCurrency(
          record.net_wage
        )})`
      ),
      {
        type: "info",
        sticky: true, // Keep the notification visible until user closes it
      }
    );
    console.log("Viewing salary details for:", record);
  }
}

// registry.category("actions").add("smartbiz_hr_interface", HrInterface);
