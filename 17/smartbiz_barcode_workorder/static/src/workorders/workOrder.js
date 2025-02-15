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
} from "@odoo/owl";
import { useService, useBus, useHistory } from "@web/core/utils/hooks";
import * as BarcodeScanner from "@web/webclient/barcode/barcode_scanner";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { View } from "@web/views/view";
import { ManualBarcodeScanner } from "@smartbiz_barcode/Components/manual_barcode";
import { url } from "@web/core/utils/urls";
import { utils as uiUtils } from "@web/core/ui/ui_service";
import { KeyPads } from "./keypads";
import { useFileViewer } from "@web/core/file_viewer/file_viewer_hook";
import { patch } from "@web/core/utils/patch";

import SmartBizBarcodePickingModel from "@smartbiz_barcode/Models/barcode_picking";

// Lets `barcodeGenericHandlers` knows those commands exist so it doesn't warn when scanned.
COMMANDS["O-CMD.MAIN-MENU"] = () => {};
COMMANDS["O-CMD.cancel"] = () => {};

const bus = new EventBus();

class ProductionActivity extends owl.Component {
  static template = "ProductionActivity";
  static props = ["activity", "closeActivity"];
  setup() {
    const userService = useService("user");
    this.state = useState({
      quantity: this.props.activity.quantity || 0,
      quality: this.props.activity.quality || 0,
      lot_id: this.props.activity.lot_id || null,
      package_id: this.props.activity.package_id || null,
      start: null, // Chưa khởi tạo, sẽ cập nhật sau khi lấy timezone
      finish: null, // Chưa khởi tạo, sẽ cập nhật sau khi lấy timezone
      timezone: userService.context.tz || "UTC", // Lấy timezone từ user_context
      packages: [],
      lots: [],
    });
    this.orm = useService("orm");
    this.notification = useService("notification");
    // console.log(this.props.activity);
    this.initializeTime(); // Lấy timezone và chuyển đổi thời gian
    this.fetchPackages(); // Lấy package
    this.fetchLots(); // Lấy lot
  }

  async initializeTime() {
    // Lấy timezone của người dùng
    const timezone = this.state.timezone;

    // Chuyển đổi thời gian start và finish sang múi giờ người dùng
    if (this.props.activity.start) {
      this.state.start = this.convertToInputFormat(
        this.props.activity.start,
        timezone
      );
    }
    if (this.props.activity.finish) {
      this.state.finish = this.convertToInputFormat(
        this.props.activity.finish,
        timezone
      );
    }
  }

  // Chuyển từ UTC sang múi giờ người dùng
  convertToInputFormat(isoDate, timezone) {
    const date = new Date(isoDate);
    const options = { timeZone: timezone, hour12: false };
    const localDate = new Intl.DateTimeFormat("en-US", {
      ...options,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    }).formatToParts(date);

    // Tạo định dạng 'YYYY-MM-DDTHH:mm'
    const year = localDate.find((part) => part.type === "year").value;
    const month = localDate.find((part) => part.type === "month").value;
    const day = localDate.find((part) => part.type === "day").value;
    const hour = localDate.find((part) => part.type === "hour").value;
    const minute = localDate.find((part) => part.type === "minute").value;

    return `${year}-${month}-${day}T${hour}:${minute}`;
  }

  // Chuyển từ múi giờ người dùng sang UTC
  convertToOdooFormat(localDateTime, timezone) {
    const localDate = new Date(localDateTime); // Input từ người dùng
    const utcDate = new Date(
      localDate.getTime() - localDate.getTimezoneOffset() * 60000
    ); // Chuyển sang UTC

    const year = utcDate.getUTCFullYear();
    const month = String(utcDate.getUTCMonth() + 1).padStart(2, "0");
    const day = String(utcDate.getUTCDate()).padStart(2, "0");
    const hours = String(utcDate.getUTCHours()).padStart(2, "0");
    const minutes = String(utcDate.getUTCMinutes()).padStart(2, "0");
    const seconds = String(utcDate.getUTCSeconds()).padStart(2, "0");

    return `${year}-${month}-${day} ${hours}:${minutes}:${seconds}`;
  }

  async save() {
    if (this.state.quantity <= 0) {
      this.notification.add("Quantity must be greater than 0", {
        type: "danger",
      });
      return;
    }
    if (this.state.quality < 0 || this.state.quality > 100) {
      this.notification.add("Quality must be between 0 and 100", {
        type: "danger",
      });
      return;
    }

    const updatedData = {
      id: this.props.activity.id,
      quantity: this.state.quantity,
      quality: this.state.quality,
      lot_id: this.state.lot_id,
      package_id: this.state.package_id,
      start: this.state.start
        ? this.convertToOdooFormat(this.state.start, this.state.timezone)
        : null,
      finish: this.state.finish
        ? this.convertToOdooFormat(this.state.finish, this.state.timezone)
        : null,
    };

    if (this.props.closeActivity) {
      this.props.closeActivity(updatedData);
    }
  }

  cancel() {
    if (this.props.closeActivity) {
      this.props.closeActivity(false);
    }
  }

  async fetchLots() {
    const lots = await this.orm.searchRead("stock.lot", [], ["name"]);
    this.state.lots = lots;
  }

  async fetchPackages() {
    const packages = await this.orm.searchRead(
      "smartbiz_mes.package",
      [],
      ["name"]
    );
    // console.log(packages)
    this.state.packages = packages;
  }
}

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
  getClasscomponet(component) {
    // console.log(component)
    let cl = " ";
    if (
      (component.quantity == component.ok_quantity &&
        component.ng_quantity == 0) ||
      component.quantity == component.ok_quantity + component.ng_quantity
    ) {
      cl += " bg-green";
    } else if (
      component.quantity > component.ok_quantity &&
      component.ok_quantity != 0
    ) {
      cl += " bg-yellow";
    } else if (
      component.quantity < component.ok_quantity ||
      component.quantity < component.ok_quantity + component.ng_quantity
    ) {
      cl += " bg-red";
    }
    return cl;
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
    "activityActions",
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

    //console.log(this.props);
  }

  getClass(line) {
    // console.log(line)
    let cl = " ";
    if (line.start && !line.finish) {
      if (!line.package_id) {
        cl += "";
      } else cl += " bg-yellow";
    }
    if (line.start && line.finish) {
      if (line.quality < 1) {
        cl += " bg-red";
      } else cl += " bg-green";
    }
    return cl;
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
    ProductionActivity,
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
    this.selectedActivity = null;
    this.state = useState({
      workOrders: [],
      selectedWorkOrder: [],
      selectedActivity: null,
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
      showPDF: true,
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
      activeTab: "Detail",
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
    });
  }
  async initData() {
    try {
      const data = await this.orm.call(
        "mrp.workorder",
        "get_orders",
        [, [["state", "in", ["progress", "pending", "ready"]]]],
        {}
      );
      this.state.workOrders = data.orders;
      this.state.originalData = [...data.orders];
      this.state.searchInput = "";
      this.state.data = data;
    } catch (error) {
      //console.error("Error loading data:", error);
      this.notification.add("Failed to load inventory data", {
        type: "danger",
      });
    }
    // this.updateButton()
  }
  changeTab(tab) {
    if (tab === "Detail") {
      this.state.activeTab = "Detail";
      // console.log(this.state.detailTitle)
    } else if (tab === "PDF") {
      this.state.activeTab = "PDF";
      // console.log(this.state.activeTab)
    }
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
    const data = await this.orm.call(
      "mrp.workorder",
      "get_orders",
      [, [["state", "in", ["progress", "pending", "ready"]]]],
      {}
    );
    if (this.state.workcentername) {
      this.state.workOrders = data.orders.filter(
        (x) => x.name === this.state.workcentername
      );
      this.state.title = this.state.workcentername;
    } else {
      this.state.workOrders = data.orders;
      // console.log(this.state.workOrders);
      // const message = _t(`Vui lòng quét khu vực sản xuất!`);
      // this.notification.add(message, { type: "warning" });
    }
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
    //console.log(component.producing_ok_quantity, component.ok_quantity);
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
        this.state.component.remain_quantity.toString();
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
    this.state.showkeypad = false;
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
      // this.initData();
    } else if (this.state.view === "ActionDetail") {
      this.state.view = "WorkOrderDetail";
      this.state.selectedComponent = null;
      this.state.selectedActivity = null;
    } else if (this.state.view === "WorkOrders") {
      this.state.view = "ScanWorkCenter";
      this.state.selectedComponent = null;
      this.state.title = "";
    } else if (this.state.view === "ProductionActivity") {
      this.state.view = "ActionDetail";
    }
  }

  async closeActivity(data) {
    console.log(data);
    if (data) {
      const get_data = await this.orm.call(
        "mrp.workorder",
        "update_activity",
        [, this.state.selectedWorkOrder.id, data],
        {}
      );
      this.state.components = get_data.components;
      this.state.selectedComponent = this.state.components.find(
        (x) => x.id == this.state.selectedComponent.id
      );
    }
    this.state.view = "ActionDetail";
  }

  async activityActions(action, id) {
    // console.log({action,id})
    if (action == "edit") {
      this.state.selectedActivity = id;
      this.state.view = "ProductionActivity";
      // console.log(this.state.selectedActivity, id);
    } else if (action == "delete") {
      if (id) {
        console.log(id)
        const get_data = await this.orm.call(
          "mrp.workorder",
          "delete_activity",
          [, this.state.selectedWorkOrder.id, id],
          {}
        );
        this.state.components = get_data.components;
        this.state.selectedWorkOrder = get_data.workOrder;
        this.state.selectedComponent = this.state.components.find(
          (x) => x.id == this.state.selectedComponent.id
        );
      }
      this.state.view = "ActionDetail";
    } else if (action == "print") {
      if (id) {
        const get_data = await this.orm.call(
          "mrp.workorder",
          "print_label",
          [, this.state.selectedWorkOrder.id, id],
          {}
        );
        this.state.components = get_data.components;
        this.state.selectedWorkOrder = get_data.workOrder;
        this.state.selectedComponent = this.state.components.find(
          (x) => x.id == this.state.selectedComponent.id
        );
      }
      this.state.view = "ActionDetail";
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
    //console.log(this.state.components);
    this.state.selectedWorkOrder = get_data.workOrder;
    this.state.title = this.state.selectedWorkOrder.name;
    console.log(this.state.selectedWorkOrder);
  }
  toggleMenu = () => {
    this.state.menuVisible = !this.state.menuVisible;
  };

  // Khi người dùng chọn một thành phần
  selectComponent(component) {
    this.state.view = "ActionDetail";
    this.state.selectedComponent = component;
    //console.log(component);
    if (component.producing_quantity == 0 && component.remain_quantity) {
      //console.log("object is not producing");
      // uibuilder.send({ component: component,type:'start',selectedWorkorder:this.state.selectedWorkOrder.id,
      // this.state.components = this.state.components;
    }
    const pdfUrl = `/web/content?model=mrp.workorder&field=worksheet&id=${this.state.selectedWorkOrder.id}`;
    this.state.showPDF = true;
    this.state.document = {
      type: "pdf",
      url: `/web/static/lib/pdfjs/web/viewer.html?file=${encodeURIComponent(
        pdfUrl
      )}`,
    };
  }

  // Mở PDF khi nhấn nút, nhận `component.id` như một tham số
  async openPDF() {
    const pdfUrl = `/web/content?model=mrp.workorder&field=worksheet&id=${this.state.selectedWorkOrder.id}`;
    this.state.showPDF = true;
    this.state.document = {
      type: "pdf",
      url: `/web/static/lib/pdfjs/web/viewer.html?file=${encodeURIComponent(
        pdfUrl
      )}`,
    };
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
        const message = _t(`Công đoạn đã hoàn tất`);
        this.notification.add(message, { type: "success" });
        this.pauseTimer();
        this.stopTimer();
        this.openWorkorder();
      },
      cancel: () => {},
      confirmLabel: _t("Có, xác nhận."),
      cancelLabel: _t("Hủy bỏ"),
    };
    this.dialog.add(ConfirmationDialog, params);

    // console.log(finish_workorder);
  }
  async printLabel() {
    const print = await this.orm.call(
      "mrp.workorder",
      "print_label",
      [, this.state.selectedWorkOrder?.id, this.state.selectedComponent?.id],
      {}
    );
    //console.log(print);
  }
  async okAction() {
    // Lấy số lượng OK đang “sản xuất dở”
    const producingOkQuantity = Number(
      this.state.selectedComponent.producing_ok_quantity
    );
    // Số lượng OK đã hoàn thành
    const okQuantity = Number(this.state.selectedComponent.ok_quantity);
    // Nhu cầu
    const totalNeeded = Number(this.state.selectedComponent.quantity);

    // Nếu quá nhu cầu => cảnh báo
    if (producingOkQuantity + okQuantity > totalNeeded) {
      const message = _t(`Số lượng đạt lớn hơn số lượng nhu cầu`);
      this.notification.add(message, { type: "warning" });
      return;
    }

    // Thay vì update_component => gọi handle_package_scan
    // Như ta thiết kế: qr_code = "", button_type = "ok_action"
    // => server logic sẽ hiểu đây là "Finish OK" (hoặc Tạo+Finish nếu chưa có).
    console.log([
        ,
        this.state.selectedWorkOrder.id,         // workorder_id
        this.state.selectedComponent.id,         // component_id
        "",                                      // qr_code
        "ok_action",                             // button_type
        false,                                   // force (nếu bạn muốn bấm force => true)
        producingOkQuantity                      // quantity
      ])
    const result = await this.orm.call(
      "mrp.workorder",
      "handle_package_scan",
      [
        ,    
        this.state.selectedWorkOrder.id,         // workorder_id
        this.state.selectedComponent.id,         // component_id
        "",                                      // qr_code
        "ok_action",                             // button_type
        false,                                   // force (nếu bạn muốn bấm force => true)
        producingOkQuantity                      // quantity
      ],
      {}
    );

    // Server trả về data => cập nhật state
    if (result && result.components && result.workOrder) {
      this.state.components = result.components;
      this.state.selectedWorkOrder = result.workOrder;
      // Tìm component vừa thay đổi
      const updatedComp = result.components.find(
        (c) => c.id === this.state.selectedComponent.id
      );
      if (updatedComp) {
        this.state.selectedComponent = updatedComp;
      }
    }
  }

  async ngAction() {
    // Lấy số lượng NG mà công nhân vừa nhập
    const producingNgQuantity = Number(
      this.state.selectedComponent.producing_ng_quantity
    );
    if (producingNgQuantity <= 0) {
      const message = _t("Số lượng NG phải lớn hơn 0");
      this.notification.add(message, { type: "warning" });
      return;
    }

    // Gọi handle_package_scan với button_type='ng_action'
    // => logic Tạo/Cập nhật activity NG => finish + trừ OK
    const result = await this.orm.call(
      "mrp.workorder",
      "handle_package_scan",
      [
        ,
        this.state.selectedWorkOrder.id, 
        this.state.selectedComponent.id,
        "",                // qr_code = rỗng
        "ng_action",       // button_type
        false,             // force
        producingNgQuantity
      ],
      {}
    );

    if (result && result.components && result.workOrder) {
      this.state.components = result.components;
      this.state.selectedWorkOrder = result.workOrder;
      const updatedComp = result.components.find(
        (c) => c.id === this.state.selectedComponent.id
      );
      if (updatedComp) {
        this.state.selectedComponent = updatedComp;
      }
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
        // const data = await this.orm.call(
        //   "mrp.workorder",
        //   "get_orders",
        //   [, [["state", "in", ["progress", "pending", "ready"]]]],
        //   {}
        // );
        // this.state.workOrders = data.orders.filter(
        //   (x) => x.name === this.state.workcentername
        // );
        this.state.title = this.state.workcentername;
        this.state.workcentername = barcodeData.record.name;
        this.openWorkorder();
        // console.log("Filtered WorkOrders:", this.state.workOrders);
      } else {
        this.notification.add(`Barcode: ${barcode} không hợp lệ!`, {
          type: "warning",
        });
        return;
      }
    }

    if (this.state.view === "ActionDetail") {
      if (barcode) {
        const data = await this.orm.call(
          "mrp.workorder",
          "handle_package_scan",
          [
            ,
            this.state.selectedWorkOrder.id,
            this.state.selectedComponent.id,
            barcode,
          ],
          {}
        );
        if (data.components && data.workOrder) {
          this.state.components = data.components;
          this.state.selectedWorkOrder = data.workOrder;
          this.state.selectedComponent = this.state.components.find(
            (x) => x.id == this.state.selectedComponent.id
          );
        }
      }
      this.state.view = "ActionDetail";
    }
  }
}

registry.category("actions").add("smartbiz_barcode.WorkOrder", WorkOrder);
