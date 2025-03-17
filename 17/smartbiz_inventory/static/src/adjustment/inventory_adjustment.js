/** @odoo-module **/
import { registry } from "@web/core/registry";
import {
  Component,
  EventBus,
  onPatched,
  onWillStart,
  useState,
  useSubEnv,
  xml,
  onMounted,
} from "@odoo/owl";
import { useService, useBus, useHistory } from "@web/core/utils/hooks";
import * as BarcodeScanner from "@web/webclient/barcode/barcode_scanner";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { View } from "@web/views/view";
import { ManualBarcodeScanner } from "@smartbiz_barcode/Components/manual_barcode";
import { url } from "@web/core/utils/urls";
import { utils as uiUtils } from "@web/core/ui/ui_service";
import SmartBizBarcodePickingModel from "@smartbiz_barcode/Models/barcode_picking";

class DetailInventoryLine extends Component {
  static template = "DetailInventoryLine";
  static props = ["line", "closeEdit"];
  setup() {
    const userService = useService("user");
    this.state = useState({
      line: this.props.line,
      lot_id: this.props.line.lot_id ? parseInt(this.props.line.lot_id) : null,
      package_id: this.props.line.package_id ? parseInt(this.props.line.package_id) : null,
      location_id: this.props.line.location_id ? parseInt(this.props.line.location_id) : null, // Thêm location_id vào state
      packages: [],
      lots: [],
      locations: [],
      Note: this.stripHtml(this.props.line.note) || '',
      quantity: 0,
    });
    this.orm = useService("orm");
    this.notification = useService("notification");
    this.dialog = useService("dialog");
    this.action = useService("action");

    onMounted(async () => {
      await this.fetchLots();
      await this.fetchPackages();
      await this.fetchLocations(); // Gọi fetchLocations()
    });
  }

  save() {
    const data = {
      id: this.state.line.id,
      lot_id: this.state.lot_id,
      package_id: this.state.package_id,
      quantity: this.state.quantity,
      location_id: this.state.location_id, // Thêm location_id vào data
      note: this.state.Note,
    }
    console.log(data)
    this.props.closeEdit(data);
  }

  close() {
    this.props.closeEdit(false);
  }

  async fetchLots() {
    try {
      const lots = await this.orm.searchRead("stock.lot", [], ["id", "name"]);
      this.state.lots = lots;
    } catch (error) {
      this.notification.add(error.message, { type: "danger" });
    }
  }

  async fetchPackages() {
    try {
      const packages = await this.orm.searchRead("stock.quant.package",  [], ["id", "name"]);
      this.state.packages = packages;
    } catch (error) {
      this.notification.add(error.message, { type: "danger" });
    }
  }

  async fetchLocations() { // Thêm hàm fetchLocations()
    try {
      const locations = await this.orm.searchRead("stock.location", [], ["id", "name", "barcode"]); // Hoặc model khác nếu cần
      this.state.locations = locations;
    } catch (error) {
      this.notification.add(error.message, { type: "danger" });
    }
  }

  // (Optional) Hàm để cập nhật state.line.location_id khi location_id thay đổi
  //  Tránh cập nhật trực tiếp props.line.location_id
  onChangeLocation(ev) {
        this.state.location_id = parseInt(ev.target.value);
        // console.log(this.state.location_id);
        // Không cập nhật this.state.line.location_id ở đây!
        // Logic lưu trữ thay đổi nên được thực hiện ở một bước riêng biệt (ví dụ, khi người dùng nhấn nút "Lưu")
    }

    stripHtml(html) {
      if (!html) {
        return '';
      }
      let tmp = document.createElement("DIV");
      tmp.innerHTML = html;
      return tmp.textContent || tmp.innerText || "";
    }
}

export class AdjustmentInventory extends Component {
  static template = "CustomInventoryViewTemplate";
  static props = [
    "action?",
    "actionId?",
    "className?",
    "globalState?",
    "resId?",
  ];
  static components = {DetailInventoryLine}
  setup() {
    this.rpc = useService("rpc");
    this.notification = useService("notification");
    this.orm = useService("orm");
    this.dialog = useService("dialog");
    this.action = useService("action");
    this.home = useService("home_menu");

    this.state = useState({
      menuVisible: false,
      search: "",
      searchInput: "",
      inventoryData: [],
      data: [],
      view: "AdjustmentInventory",
      lines: [],
      line: {},
      title: "",
      isLoading: false,
    });

    this._scrollBehavior = "smooth";
    this.isMobile = uiUtils.isSmall();
    this.barcodeService = useService("barcode");
    useBus(this.barcodeService.bus, "barcode_scanned", (ev) =>
      this.onBarcodeScanned(ev.detail.barcode)
    );
    const services = {
      rpc: this.rpc,
      orm: this.orm,
      notification: this.notification,
      action: this.action,
    };
    const model = new SmartBizBarcodePickingModel(
      "stock.quant",
      false,
      services
    );
    useSubEnv({ model });
    onWillStart(async () => {
      await this.loadInventoryData();
    });
    this.selectOrder = this.withLoading(this.selectOrder, this, 800);
    this.editItem = this.withLoading(this.editItem, this, 800);
  }

  async loadInventoryData() {
    try {
      const data = await this.orm.call(
        "smartbiz.inventory",
        "get_order",
        [,],
        {}
      );
      // this.state.inventoryData = data;
      this.state.data = data.orders;
      console.log(data);
    } catch (error) {
      console.error("Error loading data:", error);
      this.notification.add("Failed to load inventory data", {
        type: "danger",
      });
    }
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

  onSearchChange(event) {
    this.state.search = event.target.value;
    console.log(this.state.search);
    this.search();
  }

  search() {
    if (this.state.search !== "") {
      this.state.data = this.filterArrayByString(
        this.state.data,
        this.state.search
      );
    } else {
      this.state.data = this.state.data;
    }
  }
  async exit(ev) {
    if ((this.state.view === "DetailInventory")) {
      this.state.view = "AdjustmentInventory";
    } else if ((this.state.view === "AdjustmentInventory")) {
      await this.action.doAction(
        "smartbiz_barcode.smartbiz_barcode_main_menu_action"
      );
    } else if ((this.state.view === "DetailInventoryLine")) {
      this.state.view = "DetailInventory";
    }
  }

  async closeEdit(data) {
    console.log(data);
    // if (data) {
    //   const get_data = await this.orm.call(
    //     "mrp.workorder",
    //     "update_activity",
    //     [, this.state.selectedWorkOrder.id, data],
    //     {}
    //   );
    //   this.state.components = get_data.components;
    //   this.state.selectedComponent = this.state.components.find(
    //     (x) => x.id == this.state.selectedComponent.id
    //   );
    // }
    this.state.view = "DetailInventory";
  }
  toggleMenu = () => {
    this.state.menuVisible = !this.state.menuVisible;
    // console.log("object");
  };
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
  searchClick() {
    this.state.search = this.state.search ? false : true;
    this.state.searchInput = "";
    if (!this.state.search) {
      this.state.data = this.state.inventoryData;
    }
  }

  async selectOrder(id) {
    this.state.view = "DetailInventory";
      const get_data = await this.orm.call(
        "smartbiz.inventory",
        "get_data",
        [, [id]],
        {}
      );
      this.state.lines = get_data.lines;
  }
  withLoading(func, component, minLoadingTime = 500) { // Thêm tham số minLoadingTime
    return async function (...args) {
      component.state.isLoading = true;
      let loadingTimeout;
      const loadingPromise = new Promise((resolve) => {
        loadingTimeout = setTimeout(resolve, minLoadingTime);
      });
  
      try {
        const result = await Promise.race([func.apply(this, args), loadingPromise]);
        clearTimeout(loadingTimeout); // Hủy timeout nếu func hoàn thành trước
        return result;
      } catch (error) {
        console.error("Error in async function:", error);
        component.notification.add(error.message, { type: "danger" });
        throw error;
      } finally {
        component.state.isLoading = false;
      }
    };
  }

  editItem(id) {
    this.state.line = this.state.lines.find((line) => line.id === id);
    console.log(this.state.line);
    this.state.view = "DetailInventoryLine";
  }

  async processBarcode(barcode) {
    console.log(this.env.model);
    var barcodeData = await this.env.model.parseBarcodeForInventory(
      barcode,
      false,
      false,
      false
    );
    console.log(barcodeData);
    if (!barcodeData || !barcodeData.match) {
      this.notification.add(`Barcode: ${barcode} không hợp lệ!`, {
        type: "warning",
      });
      return;
    }
    if (!barcodeData.record || !barcodeData.record.products) {
      this.notification.add(
        `Không tìm thấy thông tin của barcode: ${barcode}!`,
        { type: "warning" }
      );
      return;
    }
    // if (barcodeData.match) {
    //   if (barcodeData.barcodeType == "packages") {
    //       if(!this.state.packageId){
    //           this.state.package = barcodeData.record
    //           this.state.packageProductQty = 0;
    //           for (var prod of barcodeData.record.products.filter((x) => x.product_id == this.props.move.product_id )) {
    //               this.state.packageProductQty += prod.available_quantity

    //           }
    //           this.state.packageName = barcodeData.barcode
    //           this.state.packageId = barcodeData.record.id

    //       }
    //       else if(this.state.packageId != barcodeData.record.id && !this.state.showPackageQty){
    //           this.state.processedPackages.push({
    //               id: barcodeData.record.id,
    //               name: barcodeData.barcode
    //           });
    //       }

    //   }
    //   else{
    //       const message = _t(`Barcode: ${barcode} không phải là Packages!`);
    //       this.notification.add(message, { type: "warning" });
    //   }
    // } else {

    //     const message = _t(`Không có thấy thông tin của barcode: ${barcode}!`);
    //     this.notification.add(message, { type: "warning" });
    // }
  }
}



registry
  .category("actions")
  .add("smartbiz_inventory.AdjustmentInventory", AdjustmentInventory);
