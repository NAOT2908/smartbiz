/** @odoo-module **/
import { _t } from "@web/core/l10n/translation";
import { COMMANDS } from "@barcodes/barcode_handlers";
import { registry } from "@web/core/registry";
import { loadJS } from "@web/core/assets";
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
} from "@odoo/owl";
import { useService, useBus, useHistory } from "@web/core/utils/hooks";

import { Dashboard } from "./Dashboard";

export class WorkOrderDashboard extends Component {
  static template = "WorkOrderDashboard";
  static components = { Dashboard };

  setup() {
    this.rpc = useService("rpc");
    this.orm = useService("orm");
    this.notification = useService("notification");
    this.dialog = useService("dialog");
    this.action = useService("action");
    this.home = useService("home_menu");
    this.state = useState({
      line: "1",
      headerValue: "38",
      productionDate: this.getFormattedDate(new Date()),
      shift: "1",
      dashboardData: [],
      faultyData: [],
      search: "",
      maxStepValue: 0,
      view: "WorkOrderDashboard",
      menuVisible: false,
    });
    const selectedDate = new Date();
    const formattedDate = selectedDate.toISOString().split("T")[0]; // Chuyển đổi thành yyyy-mm-dd
    this.state.productionDate = formattedDate;
    // uibuilder.send({report_date:formattedDate});

    this.onDateChange = this.onDateChange.bind(this);
    this.onShiftChange = this.onShiftChange.bind(this);
    onWillStart(async () => {
      await this.data();
      await loadJS(
        "https://cdn.jsdelivr.net/npm/exceljs@4.4.0/dist/exceljs.min.js"
      );
    });
    // Gọi lại dữ liệu mỗi 1-2 giây
    // this.intervalId = setInterval(() => {
    //   this.data();
    // }, 5000);

    // onWillUnmount(() => {
    //   clearInterval(this.intervalId);
    // });
  }

  async data() {
    const get_dashboard_data = await this.orm.call(
      "mrp.workorder",
      "get_dashboard_data",
      [, this.state.productionDate],
      {}
    );

    const get_faulty_data = await this.orm.call(
      "mrp.workorder",
      "get_faulty_data",
      [, this.state.productionDate],
      {}
    );
    this.state.dashboardData = get_dashboard_data.data;
    this.state.steps = get_dashboard_data.steps;
    this.state.faultyData = get_faulty_data;

    // console.log(get_dashboard_data, get_faulty_data);
  }

  toggleMenu = () => {
    this.state.menuVisible = !this.state.menuVisible;
  };

  changedashboard = (tab) => {
    if (tab === "WorkOrderDashboard") {
      this.state.view = "WorkOrderDashboard";
    } else if (tab === "Dashboard") {
      this.state.view = "Dashboard";
    }
  };

  getFormattedDate(date) {
    return date.toISOString().split("T")[0]; // Chuyển đổi thành yyyy-mm-dd
  }

  onDateChange(event) {
    const selectedDate = new Date(event.target.value);
    const formattedDate = selectedDate.toISOString().split("T")[0]; // Chuyển đổi thành yyyy-mm-dd
    this.state.productionDate = formattedDate;
    console.log(formattedDate);
    this.data();
  }

  onShiftChange(event) {
    this.state.shift = event.target.value;
    this.data();
  }
  formatFloatToTime(floatTime) {
    const hours = Math.floor(floatTime);
    const minutes = Math.round((floatTime - hours) * 60);
    return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(
      2,
      "0"
    )}`;
  }

  onSearchClick() {
    if (this.state.search !== "") {
      this.state.dashboardData = this.filterArrayByString(
        this.state.dashboardData,
        this.state.search
      );
    } else {
      this.data();
    }
  }

  onSearchChange(event) {
    this.state.search = event.target.value;
    console.log(this.state.search);
    this.onSearchClick();
  }

  filterArrayByString(array, queryString) {
    const queryStringLower = queryString.toLowerCase();
    return array.filter((obj) => {
      // Duyệt qua mỗi key của object để kiểm tra
      return Object.keys(obj).some((key) => {
        const value = obj[key];
        // Chỉ xét các giá trị là chuỗi hoặc số
        if (typeof value === "string" || typeof value === "number") {
          return value.toString().toLowerCase().includes(queryStringLower);
        }
        return false;
      });
    });
  }

  _fetchData() {
    const { productionDate, shift } = this.state;
    // Thực hiện logic để lấy dữ liệu từ Node-RED hoặc từ hệ thống Odoo với productionDate và shift.
  }

  async downloadExcel() {
    const workbook = new ExcelJS.Workbook();

    // === Tạo worksheet "Tiến độ sản xuất" ===
    const sheet1 = workbook.addWorksheet("Tiến độ sản xuất");
    const headers1 = [
      "STT",
      "KH",
      "Lot",
      "Sản phẩm",
      "Số lượng",
      "Thời gian tiêu chuẩn",
      "Thời gian thực tế",
      ...this.state.steps,
    ];
    // sheet1.addRow(headers1).font = { bold: true };
    sheet1.addRow(headers1).eachCell((cell) => {
      cell.font = { bold: true, color: { argb: "FFFFFFFF" } }; // Chữ màu trắng
      cell.fill = {
        type: "pattern",
        pattern: "solid",
        fgColor: { argb: "FF008cba" }, // Màu nền xanh nhạt (#B8CCE4)
      };
      cell.alignment = { horizontal: "center", vertical: "middle" }; // Căn giữa
    });

    this.state.dashboardData.forEach((row) => {
      const rowData = [
        row.stt,
        row.kh || "",
        row.lot,
        row.item,
        row.so_luong,
        row.thoi_gian_tieu_chuan,
        row.thoi_gian_thuc_te,
        ...this.state.steps.map((step) => row[step] || "-"),
      ];
      sheet1.addRow(rowData);
    });

    // === Tạo worksheet "Tiến độ sản phẩm lỗi" ===
    const sheet2 = workbook.addWorksheet("Tiến độ sản phẩm lỗi");
    if (this.state.faultyData.length > 0) {
      const headers2 = Object.keys(this.state.faultyData[0]);
      sheet2.addRow(headers2).eachCell((cell) => {
        cell.font = { bold: true, color: { argb: "FFFFFFFF" } }; // Chữ màu trắng
        cell.fill = {
          type: "pattern",
          pattern: "solid",
          fgColor: { argb: "FF008cba" }, // Màu nền xanh nhạt (#B8CCE4)
        };
        cell.alignment = { horizontal: "center", vertical: "middle" }; // Căn giữa
      });

      this.state.faultyData.forEach((row) => {
        const rowData = headers2.map((key) =>
          row[key] === 0 ? "-" : row[key]
        );
        sheet2.addRow(rowData);
      });
    }

    
    // === Xuất file Excel ===
    const buffer = await workbook.xlsx.writeBuffer();
    const blob = new Blob([buffer], {
      type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    });
    const url = URL.createObjectURL(blob);

    const a = document.createElement("a");
    a.href = url;
    a.download = "tien_do.xlsx";
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  }
}

registry.category("actions").add("smartbiz_dashboard", WorkOrderDashboard);
