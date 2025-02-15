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
} from "@odoo/owl";
import { useService, useBus, useHistory } from "@web/core/utils/hooks";
import * as BarcodeScanner from "@web/webclient/barcode/barcode_scanner";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { View } from "@web/views/view";
import { ManualBarcodeScanner } from "../Components/manual_barcode";
import { url } from "@web/core/utils/urls";
import { utils as uiUtils } from "@web/core/ui/ui_service";
import { KeyPads } from "./keypads";
import { useFileViewer } from "@web/core/file_viewer/file_viewer_hook";
import { patch } from "@web/core/utils/patch";

import SmartBizBarcodePickingModel from "../Models/barcode_picking";
// Lets `barcodeGenericHandlers` knows those commands exist so it doesn't warn when scanned.
COMMANDS["O-CMD.MAIN-MENU"] = () => {};
COMMANDS["O-CMD.cancel"] = () => {};

const bus = new EventBus();

class WorkOrderList extends Component {
  static template = "WorkOrderList";
  static props = [
    "workOrders",
    "selectWorkOrder",
    "selectedWorkOrder",
    "searchQuery",
    "searchWorkOrders",
    "stateMapping",
  ];

  setup() {
    this.rpc = useService("rpc");
    this.orm = useService("orm");
    this.notification = useService("notification");
    this.dialog = useService("dialog");
    this.action = useService("action");
    this.home = useService("home_menu");
    // this.state = useState({
    //   workOrders: this.props.workOrder,
    // });
    // console.log(this.props.selectedWorkOrder);
  }
}

class WorkOrderDetail extends Component {
  static template = "WorkOrderDetail";
  static props = [
    "workOrder",
    "startWorkOrder",
    "pauseWorkOrder",
    "stopWorkOrder",
    "showStart",
    "showStop",
    "showPause",
    "activeButton",
    "timer",
  ];
  setup() {
    this.rpc = useService("rpc");
    this.orm = useService("orm");
    this.notification = useService("notification");
    this.dialog = useService("dialog");
    this.action = useService("action");
    this.home = useService("home_menu");

    // this.state = useState({
    //   workOrders: this.props.workOrder,
    // });

    // console.log(this.props.workOrder);
  }
  floatToTimeString(minutes) {
    if (minutes === undefined || minutes === null || isNaN(minutes)) {
      return "-";
    }

    // Tính toán số ngày, giờ, phút và giây
    const days = Math.floor(minutes / 1440); // 1440 phút trong một ngày
    const remainingMinutesAfterDays = minutes % 1440;

    const hours = Math.floor(remainingMinutesAfterDays / 60);
    const remainingMinutes = Math.floor(remainingMinutesAfterDays % 60);
    const seconds = Math.floor(
      (remainingMinutesAfterDays - (hours * 60 + remainingMinutes)) * 60
    );

    // Định dạng chuỗi thời gian
    let formattedTime = `${String(hours).padStart(2, "0")}:${String(
      remainingMinutes
    ).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;

    if (days > 0) {
      formattedTime = `${days} ngày ${formattedTime}`;
    }

    return formattedTime;
  }
}

class ComponentList extends Component {
  static template = "ComponentList";
  static props = [
    "components",
    "selectComponent",
    "selectedComponent",
    "closeKeypad",
    "select",
  ];

  setup() {
    this.rpc = useService("rpc");
    this.orm = useService("orm");
    this.notification = useService("notification");
    this.dialog = useService("dialog");
    this.action = useService("action");
    this.home = useService("home_menu");

    // this.state = useState({
    //   workOrders: this.props.workOrder,
    // });

    // console.log(this.props.components);
  }
}

class ActionDetail extends Component {
  static template = "ActionDetail";
  static props = [
    "component",
    "okAction",
    "ngAction",
    "updateQuantity",
    "showOK",
    "showNG",
    "showPrint",
    "printLabel",
    "openPDF",
    "showKeypad",
  ];
  static components = { KeyPads };

  setup() {
    this.rpc = useService("rpc");
    this.orm = useService("orm");
    this.notification = useService("notification");
    this.dialog = useService("dialog");
    this.action = useService("action");
    this.home = useService("home_menu");

    this.state = useState({
      keyPadTitle: {},
    });

    console.log(this.props.component);
  }
}

class ActionDocument extends Component {
  static template = "ActionDocument";
  static props = ["document", "closePDF"];
}

export class WorkOrder extends Component {
  static components = {
    WorkOrderList,
    WorkOrderDetail,
    ComponentList,
    ActionDetail,
    ActionDocument,
    KeyPads,
  };
  static template = "WorkOrder";

  setup() {
    this.rpc = useService("rpc");
    this.orm = useService("orm");
    this.notification = useService("notification");
    this.dialog = useService("dialog");
    this.action = useService("action");
    this.home = useService("home_menu");
    this.fileViewer = useFileViewer();
    this.store = useService("mail.store");

    this.openPDF = this.openPDF.bind(this);

    this.state = useState({
      workOrders: [],
      selectedWorkOrder: [],
      components: [],
      selectedComponent: null,
      document: null,
      searchQuery: "",
      showStart: true,
      showStop: true,
      showPause: true,
      showOK: true,
      showNG: true,
      showPrint: true,
      showPDF: false,
      showkeypad: false,
      view: "ScanWorkCenter",
      menuVisible: false,
      search: false,
      searchInput: "",
      originalData: [],
      title: "",
      keyPadTitle: {},
      activeButton: null,
      codeworkcenter: "",
      workcentername: "",
      username: "",
      data: [],
      component: [],
      currentQuantityField: "",
      timer: "00:00:00",
      intervalId: null,
      elapsedTime: 0,
    });

    this._scrollBehavior = "smooth";
    this.isMobile = uiUtils.isSmall();
    this.barcodeService = useService("barcode");
    useBus(this.barcodeService.bus, "barcode_scanned", (ev) =>
      this.onBarcodeScanned(ev.detail.barcode)
    );
    this.stateMapping = {
      progress: "Đang thực hiện",
      pending: "Đang chờ",
      ready: "Sẵn sàng",
      waiting: "Đang đợi",
    };
    const services = {
      rpc: this.rpc,
      orm: this.orm,
      notification: this.notification,
      action: this.action,
    };
    const model = new SmartBizBarcodePickingModel(
      "mrp.workorder",
      false,
      services
    );
    useSubEnv({ model });
    onWillStart(async () => {
      await this.initData();
      // this.pdfUrl = this.props.pdfUrl; // URL của file PDF
      // this.pdfjsLib = await import("../lib/pdf.min.mjs");
    });
  }
  async initData() {
    try {
      const data = await this.orm.call(
        "mrp.workorder",
        "get_orders",
        [, [["state", "in", ["progress", "pending", "ready", "waiting"]]]],
        {}
      );
      this.state.workOrders = data.orders;
      this.state.originalData = [...data.orders];
      this.state.searchInput = "";
      this.state.data = data;
      console.log(data);
    } catch (error) {
      console.error("Error loading data:", error);
      this.notification.add("Failed to load inventory data", {
        type: "danger",
      });
    }
    // this.updateButton()
  }
  formatTime(seconds) {
    const hrs = String(Math.floor(seconds / 3600)).padStart(2, "0");
    const mins = String(Math.floor((seconds % 3600) / 60)).padStart(2, "0");
    const secs = String(seconds % 60).padStart(2, "0");
    return `${hrs}:${mins}:${secs}`;
  }
  startTimer() {
    if (this.state.intervalId) return; // Nếu đang chạy, không làm gì
    // Lưu mốc thời gian bắt đầu
    this.state.startTime = Date.now() - this.state.elapsedTime * 1000;
    // Hiển thị ngay giá trị đầu tiên
    this.updateTimer();

    // Cập nhật thời gian mỗi giây
    const intervalId = setInterval(() => {
      this.updateTimer();
    }, 1000);

    this.state.intervalId = intervalId;
  }

  updateTimer() {
    // Tính toán thời gian đã trôi qua
    const now = Date.now();
    this.state.elapsedTime = Math.floor((now - this.state.startTime) / 1000);
    this.state.timer = this.formatTime(this.state.elapsedTime);
  }

  stopTimer() {
    if (this.state.intervalId) {
      clearInterval(this.state.intervalId); // Dừng bộ đếm
      this.state.intervalId = null;
    }

    // Reset giá trị bộ đếm
    this.state.elapsedTime = 0;
    this.state.timer = "00:00:00";
    this.state.startTime = null;
  }

  pauseTimer() {
    if (this.state.intervalId) {
      clearInterval(this.state.intervalId); // Tạm dừng bộ đếm
      this.state.intervalId = null;
    }
  }

  async openWorkorder() {
    this.state.view = "WorkOrders";
    if (this.state.workcentername) {
      this.state.workOrders = this.state.data.orders.filter(
        (x) => x.name === this.state.workcentername
      );
      this.state.title = this.state.workcentername;
    }
    // else {
    //   const message = _t(`Vui lòng quét khu vực sản xuất!`);
    //   this.notification.add(message, { type: "warning" });
    // }
  }
  Resetscan() {
    this.state.workcentername = "";
    this.state.username = "";
    this.initData();
  }
  handleInput(event) {
    this.state.searchInput = event.target.value;
    this.search(); // Gọi hàm tìm kiếm
  }
  showKeypad = (keyPadTitle, component, type) => {
    this.state.keyPadTitle = keyPadTitle;
    this.state.showkeypad = true;
    this.state.component = component;
    this.state.currentQuantityField = type;
    console.log(component.producing_ok_quantity, component.ok_quantity);
    // this.state.selectedComponent.producing_ok_quantity + this.state.selectedComponent.ok_quantity
  };
  keyClick = (option) => {
    option = option.toString();
    const quantityField =
      this.state.currentQuantityField === "ok"
        ? "producing_ok_quantity"
        : "producing_ng_quantity";

    if (!this.state.component[quantityField]) {
      this.state.component[quantityField] = 0;
    }
    if (option == "cancel") {
      this.state.showkeypad = false;
    } else if (option == "confirm") {
      this.state.showkeypad = false;
      // this.updateButton()
      // this.state.component[quantityField] = 0;
    } else if (option == "DEL") {
      this.state.component[quantityField] = "0"; // Hoặc có thể xóa ký tự
    } else if (option == "C") {
      var string = this.state.component[quantityField].toString();
      this.state.component[quantityField] = string.substring(
        0,
        string.length - 1
      );
    } else if (option.includes("++")) {
      this.state.component[quantityField] =
        this.state.component.quantity_need.toString();
    } else if (option.includes("+")) {
      this.state.component[quantityField] = (
        parseFloat(this.state.component[quantityField]) + 1
      ).toString();
    } else if (option.includes("-")) {
      this.state.component[quantityField] = (
        parseFloat(this.state.component[quantityField]) - 1
      ).toString();
    } else {
      if (
        !(
          this.state.component[quantityField].toString().includes(".") &&
          option == "."
        )
      )
        if (this.state.component[quantityField] != 0)
          this.state.component[quantityField] =
            this.state.component[quantityField].toString() + option;
        else this.state.component[quantityField] = option;
    }
  };
  closeKeypad = () => {
    this.state.showKeypad = false;
  };
  async search() {
    const query = this.state.searchInput.trim().toLowerCase();
    if (this.state.view === "WorkOrders") {
      if (this.state.workcentername) {
        this.state.workOrders = this.state.data.orders.filter(
          (x) => x.name === this.state.workcentername
        );
        if (query) {
          this.state.workOrders = this.filterArrayByString(
            this.state.workOrders,
            query
          );
        }
      } else {
        if (query) {
          this.state.workOrders = this.filterArrayByString(
            this.state.data.orders,
            query
          );
        } else {
          this.state.workOrders = this.state.data.orders;
        }
      }
    } else if (this.state.view === "WorkOrderDetail") {
      const data = await this.orm.call(
        "mrp.workorder",
        "get_data",
        [, [this.state.selectedWorkOrder.id]],
        {}
      );
      if (query) {
        this.state.components = this.filterArrayByString(
          data.components,
          query
        );
      } else {
        this.state.components = data.components;
      }
    }
  }

  searchClick() {
    this.state.search = !this.state.search; // Bật/tắt chế độ tìm kiếm
    this.state.searchInput = ""; // Xóa dữ liệu tìm kiếm
    // this.state.workOrders = [...this.state.originalData];
  }

  filterArrayByString(array, queryString) {
    const queryStringLower = queryString.toLowerCase();
    return array.filter((obj) => {
      return Object.keys(obj).some((key) => {
        const value = obj[key];
        if (value && (typeof value === "string" || typeof value === "number")) {
          return value.toString().toLowerCase().includes(queryStringLower);
        }
        return false;
      });
    });
  }

  async exit(ev) {
    if (this.state.view === "ScanWorkCenter") {
      await this.action.doAction(
        "smartbiz_barcode.smartbiz_barcode_main_menu_action"
      );
    } else if (this.state.view === "WorkOrderDetail") {
      this.state.view = "WorkOrders";
      // this.stopTimer()
      // this.state.title = ""
      this.initData();
    } else if (this.state.view === "ActionDetail") {
      this.state.view = "WorkOrderDetail";
      this.state.selectedComponent = null;
    } else if (this.state.view === "WorkOrders") {
      this.state.view = "ScanWorkCenter";
      this.state.selectedComponent = null;
      this.state.title = "";
    }
  }
  select(id) {
    // this.state.selectedItem = id;
    // console.log(id);
  }
  updateButton() {
    this.state.showStart = false;
    this.state.showStop = false;
    this.state.showPause = false;
    this.state.showOK = false;
    this.state.showNG = false;
    this.state.showPrint = false;
    if (this.state.selectedWorkOrder) {
      if (
        (this.state.selectedWorkOrder?.state == "progress" &&
          !this.state.selectedWorkOrder?.is_user_working) ||
        (this.state.selectedWorkOrder?.state != "progress" &&
          this.state.selectedWorkOrder)
      )
        this.state.showStart = true;

      if (
        this.state.selectedWorkOrder?.state == "progress" &&
        this.state.selectedWorkOrder?.is_user_working
      ) {
        this.state.showStop = true;
        this.state.showPause = true;
      }
    }
    if (
      !this.state.workOrders.some(
        (workOrder) => workOrder.id === this.state.selectedWorkOrder.id
      )
    ) {
      this.state.selectedWorkOrder = null;
      this.state.components = [];
    }
    if (
      !this.state.components.some(
        (comp) => comp.id === this.state.selectedComponent?.id
      )
    ) {
      this.state.selectedComponent = null;
    }
    if (
      this.state.selectedComponent?.remain_quantity ||
      this.state.selectedComponent?.producing_quantity
    ) {
      this.state.showOK = true;
      this.state.showNG = true;
      this.state.showPrint = true;
    }
  }

  async selectWorkOrder(id) {
    this.state.view = "WorkOrderDetail";
    const get_data = await this.orm.call(
      "mrp.workorder",
      "get_data",
      [, [id]],
      {}
    );
    this.state.components = get_data.components;
    this.state.selectedWorkOrder = get_data.workOrder;
    this.state.title = this.state.selectedWorkOrder.name;
    // console.log(this.state.components, this.state.selectedWorkOrder);
  }
  toggleMenu = () => {
    this.state.menuVisible = !this.state.menuVisible;
    // console.log("object");
  };

  // Khi người dùng chọn một thành phần
  selectComponent(component) {
    this.state.view = "ActionDetail";
    this.state.selectedComponent = component;
    console.log(component);
    if (component.producing_quantity == 0 && component.remain_quantity) {
      console.log("object is not producing");
      // uibuilder.send({ component: component,type:'start',selectedWorkorder:this.state.selectedWorkOrder.id,
      // this.state.components = this.state.components;
    }
  }

  // Mở PDF khi nhấn nút, nhận `component.id` như một tham số
  async openPDF() {
    const pdfUrl = `/web/content?model=mrp.workorder&field=worksheet&id=${this.state.selectedComponent.id}`;
    // console.log(this.state.selectedComponent.id, this.isMobile);

    if (this.isMobile) {
      // Tạo URL cho file PDF dựa trên componentId
      const action = {
        type: "ir.actions.act_url",
        url: pdfUrl,
        target: "_self", // Mở trong cửa sổ mới
      };

      try {
        await this.action.doAction(action);
      } catch (error) {
        console.error("Error opening PDF:", error);
      }
    } else {
      this.state.showPDF = true;
      this.state.document = {
        type: "pdf",
        url: pdfUrl,
      }; // Load PDF với pdf.js
    }
  }

  closePDF = () => {
    this.state.showPDF = false;
  };
  searchWorkOrders() {
    // Giả lập tìm kiếm công đoạn
    const query = this.state.searchQuery.toLowerCase();
    this.state.workOrders = this.state.workOrders.filter(
      (order) =>
        order.name.toLowerCase().includes(query) ||
        order.product.toLowerCase().includes(query)
    );
    // console.log(this.state.workOrders, query);
  }

  async startWorkOrder() {
    const start_workorder = await this.orm.call(
      "mrp.workorder",
      "start_workorder",
      [, this.state.selectedWorkOrder?.id],
      {}
    );
    // console.log(start_workorder);
    if (start_workorder?.workOrder) {
      this.state.selectedWorkOrder = start_workorder.workOrder;
      // this.state.showPause = true;
    }
    this.startTimer();
  }
  async pauseWorkOrder() {
    const pause_workorder = await this.orm.call(
      "mrp.workorder",
      "pause_workorder",
      [, this.state.selectedWorkOrder?.id],
      {}
    );
    if (pause_workorder?.workOrder) {
      this.state.selectedWorkOrder = pause_workorder.workOrder;
      // this.state.showStop = true;
    }
    // console.log(pause_workorder);
    this.pauseTimer();
  }
  async stopWorkOrder() {
    const params = {
      title: _t("Xác nhận đơn"),
      body: _t("Bạn có chắc chắn muốn hoàn thành."),
      confirm: async () => {
        const finish_workorder = await this.orm.call(
          "mrp.workorder",
          "finish_workorder",
          [, this.state.selectedWorkOrder?.id],
          {}
        );
        if (finish_workorder?.workOrder) {
          this.state.selectedWorkOrder = finish_workorder.workOrder;
        }
      },
      cancel: () => {},
      confirmLabel: _t("Có, xác nhận."),
      cancelLabel: _t("Hủy bỏ"),
    };
    this.dialog.add(ConfirmationDialog, params);
    this.stopTimer();
    // console.log(finish_workorder);
  }
  async printLabel() {
    // uibuilder.send({
    //     selectedWorkorder: this.state.selectedWorkOrder?.id,
    //     workorder_id: this.state.selectedWorkOrder?.id,
    //     component_id: this.state.selectedComponent?.id,
    //     printLabel:true,
    // });
    const print = await this.orm.call(
      "mrp.workorder",
      "print_label",
      [, this.state.selectedWorkOrder?.id, this.state.selectedComponent],
      {}
    );
    console.log(print);
  }
  async okAction() {
    const producingOkQuantity = Number(this.state.selectedComponent.producing_ok_quantity);
    const okQuantity = Number(this.state.selectedComponent.ok_quantity);
    const quantity = Number(this.state.selectedComponent.quantity);
    if ((producingOkQuantity + okQuantity) <= quantity) {
      const result = await this.orm.call(
        "mrp.workorder",
        "update_component",
        [, "ok_action", this.state.selectedComponent],
        {}
      );
      const updatedComponents = result?.components || [];
      const updatedComponent = updatedComponents.find(
        (c) => c.id === this.state.selectedComponent?.id
      );

      if (updatedComponent) {
        this.state.selectedComponent = updatedComponent;
        // this.selectComponent(updatedComponent)
      }
      this.state.components = updatedComponents;
      // console.log("Updated component:", this.state.selectedComponent);
    } else {
      const message = _t(`Số lượng đạt lớn hơn số lượng nhu cầu`);
      this.notification.add(message, { type: "warning" });
    }
  }
  async ngAction() {
    if (this.state.selectedComponent.producing_ng_quantity > 0) {
      const result = await this.orm.call(
        "mrp.workorder",
        "update_component",
        [, "ng_action", this.state.selectedComponent],
        {}
      );
      const updatedComponents = result?.components || [];
      const updatedComponent = updatedComponents.find(
        (c) => c.id === this.state.selectedComponent?.id
      );

      if (updatedComponent) {
        this.state.selectedComponent = updatedComponent;
        // this.selectComponent(updatedComponent)
      }
      this.state.components = updatedComponents;
      // console.log("Updated component:", this.state.selectedComponent);
    }
  }
  async updateQuantity(type, operation) {
    if (type == "ok") {
      if (operation == "+") {
        this.state.selectedComponent.producing_ok_quantity += 1;
      }
      if (operation == "-") {
        this.state.selectedComponent.producing_ok_quantity -= 1;
      }

      await this.orm.call(
        "mrp.workorder",
        "update_component",
        [, "ok", this.state.selectedComponent],
        {}
      );
    }
    if (type == "ng") {
      if (operation == "+") {
        this.state.selectedComponent.producing_ng_quantity += 1;
      }
      if (operation == "-") {
        this.state.selectedComponent.producing_ng_quantity -= 1;
      }
      await this.orm.call(
        "mrp.workorder",
        "update_component",
        [, "ng", this.state.selectedComponent],
        {}
      );
    }
  }

  setScanTarget(target) {
    this.state.scanTarget = target; // Lưu trường đang quét
  }

  updateScanValue(value) {
    if (this.state.scanTarget === "productionArea") {
      this.state.productionArea = value; // Cập nhật khu vực sản xuất
    } else if (this.state.scanTarget === "username") {
      this.state.username = value; // Cập nhật người dùng
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

  async processBarcode(barcode) {
    let barcodeData = null;

    if (this.state.view === "ScanWorkCenter") {
      // Gọi parseBarcodeForWorkcenter cho chế độ ScanWorkCenter
      barcodeData = await this.env.model.parseBarcodeForWorkcenter(
        barcode,
        false,
        false,
        false
      );
      console.log(barcodeData);
      if (barcodeData && barcodeData.match) {
        // console.log("Barcode Data (ScanWorkCenter):", barcodeData);
        if (barcodeData.barcodeType === "employees") {
          this.state.username = barcodeData.record.name;
        }
        if (barcodeData.barcodeType === "workcenters") {
          this.state.codeworkcenter = barcodeData.barcode;
          this.state.workcentername = barcodeData.record.name;
          // this.state.workOrders = this.state.data.orders.filter(
          //   (x) => x.name === barcodeData.record.name
          // );
        }

        // console.log(this.state.data)
      } else {
        this.notification.add(`Barcode: ${barcode} không hợp lệ!`, {
          type: "warning",
        });
        return;
      }
    }

    if (this.state.view === "WorkOrders") {
      // Gọi parseBarcodeForWorkcenter cho chế độ WorkOrders
      barcodeData = await this.env.model.parseBarcodeForWorkcenter(
        barcode,
        false,
        false,
        false
      );

      if (barcodeData && barcodeData.match) {
        console.log("Barcode Data (WorkOrders):", barcodeData);

        // Lọc danh sách workOrders theo record name
        // this.state.workOrders = this.state.originalData.orders.filter(
        //     (x) => x.name === barcodeData.record.name
        // );

        console.log("Filtered WorkOrders:", this.state.workOrders);
      } else {
        this.notification.add(`Barcode: ${barcode} không hợp lệ!`, {
          type: "warning",
        });
        return;
      }
    }
  }
}

registry.category("actions").add("smartbiz_barcode.WorkOrder", WorkOrder);
