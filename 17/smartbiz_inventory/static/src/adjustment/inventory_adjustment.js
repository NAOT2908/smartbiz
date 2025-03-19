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
import { Selector }from "./Selector";

class DetailInventoryLine extends Component {
  static template = "DetailInventoryLine";
  static props = ["line", "closeEdit"];
  static components = { Selector };

  setup() {
    this.userService = useService("user");
    this.orm = useService("orm");
    this.notification = useService("notification");
    this.dialog = useService("dialog");
    this.action = useService("action");

    // Khởi tạo state với các giá trị mặc định, tránh gán trực tiếp vào props
    this.state = useState({
      line: { ...this.props.line },  // Chứa tất cả dữ liệu chỉnh sửa
      products: [],
      lots: [],
      packages: [],
      locations: [],
      showSelector: false,
      selectorTitle: "",
      records: [],
      multiSelect: false,
      isSelector: true,
      quantity: this.props.line.quantity_counted || 0,
      Note: this.stripHtml(this.props.line.note) || "",
    });

    onMounted(async () => {
      await this.loadData();
    });
  }

  async loadData() {
    try {
      await Promise.all([
        this.fetchLots(),
        this.fetchPackages(),
        this.fetchLocations(),
        this.fetchProducts()
      ]);
    } catch (error) {
      this.notification.add(error.message, { type: "danger" });
    }
  }

  async fetchProducts() {
    try {
      const products = await this.orm.searchRead("product.product", [], ["id", "name", "display_name", "barcode", "default_code"]);
      this.state.products = products;
    } catch (error) {
      this.notification.add(error.message, { type: "danger" });
    }
  }

  async fetchLots() {
    try {
      const lots = await this.orm.searchRead("stock.lot", [], ["id", "name", "product_id"]);

      this.state.lots = this.state.line.product_id ? lots.filter(l => l.product_id && l.product_id[0] === this.state.line.product_id)  : lots;
    } catch (error) {
      this.notification.add(error.message, { type: "danger" });
    }
  }

  async fetchPackages() {
    try {
      const packages = await this.orm.searchRead("stock.quant.package", [], ["id", "name"]);
      this.state.packages = packages;
    } catch (error) {
      this.notification.add(error.message, { type: "danger" });
    }
  }

  async fetchLocations() {
    try {
      const locations = await this.orm.searchRead("stock.location", [], ["id", "name", "barcode"]);
      this.state.locations = locations;
    } catch (error) {
      this.notification.add(error.message, { type: "danger" });
    }
  }

  save() {
    this.state.line.quantity_counted = this.state.quantity
    this.state.line.note = this.state.Note
    this.props.closeEdit(this.state.line);
  }

  close() {
    this.props.closeEdit(false);
  }

  stripHtml(html) {
    if (!html) return "";
    const tmp = document.createElement("DIV");
    tmp.innerHTML = html;
    return tmp.textContent || tmp.innerText || "";
  }


  openSelector = async (option) => {
    if (option == 1) {
    this.records = this.state.products;
    this.multiSelect = false;
    this.selectorTitle = "Sản phẩm";
    } else if (option == 2) {
    //Chọn số Lot
    this.records = this.state.lots
    this.multiSelect = false;
    this.selectorTitle = "Chọn số Lô/Sê-ri";
    } else if (option == 3) {
    //Địa điểm nguồn
    this.records = this.state.locations;
    this.multiSelect = false;
    this.selectorTitle = "Chọn vị trí";
    } else if (option == 4) {
    //Chọn gói đích
    this.records = this.state.packages;
    this.multiSelect = false;
    this.selectorTitle = "Chọn kiện hàng";
    }
    this.state.showSelector = true;
  };


  closeSelector = async (data, title = "") => {
    if (data) {
        if (title === "Sản phẩm") {
            this.state.line.product_id = data.id;
            this.state.line.product_name = data.display_name || data.name;
            await this.fetchLots();
        } else if (title === "Chọn vị trí") {
            this.state.line.location_id = data.id;
            this.state.line.location_name = data.name;
        } else if (title === "Chọn số Lô/Sê-ri") {
            this.state.line.lot_id = data.id;
            this.state.line.lot_name = data.name;
        } else if (title === "Chọn kiện hàng") {
            this.state.line.package_id = data.id;
            this.state.line.package_name = data.name;
        }
    }
    this.clearSelector();
  };
  


  clearSelector() {
    this.state.records = [];
    this.state.multiSelect = false;
    this.state.selectorTitle = "";
    this.state.showSelector = false;
    this.state.isSelector = true;
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
  static components = { DetailInventoryLine, Selector };
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
      selectedOrder: null,
      status: "X",
      selectedLine: null,
    });

    this.stateMapping = {
      pending: "X",
      counting: "V",
    };

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
      "smartbiz.inventory",
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
    if (this.state.view === "DetailInventory") {
      this.state.view = "AdjustmentInventory";
    } else if (this.state.view === "AdjustmentInventory") {
      await this.action.doAction(
        "smartbiz_barcode.smartbiz_barcode_main_menu_action"
      );
    } else if (this.state.view === "DetailInventoryLine") {
      this.state.view = "DetailInventory";
    }
  }

  async closeEdit(data) {
    // console.log(data);
    if (data) {
      const get_data = await this.orm.call(
        "smartbiz.inventory",
        "save_order",
        [, this.state.selectedOrder, data],
        {}
      );
      console.log(get_data)
      // this.state.data = get_data.orders;
      this.state.lines = get_data.lines;
    }
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
    this.state.selectedOrder = id;
    // console.log(id)
    const get_data = await this.orm.call(
      "smartbiz.inventory",
      "get_data",
      [, [id]],
      {}
    );
    this.state.lines = get_data.lines;
  }
  withLoading(func, component, minLoadingTime = 500) {
    // Thêm tham số minLoadingTime
    return async function (...args) {
      component.state.isLoading = true;
      let loadingTimeout;
      const loadingPromise = new Promise((resolve) => {
        loadingTimeout = setTimeout(resolve, minLoadingTime);
      });

      try {
        const result = await Promise.race([
          func.apply(this, args),
          loadingPromise,
        ]);
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
    if(id){
      this.state.line = this.state.lines.find((line) => line.id === id);
      console.log(this.state.line);
    }else{
      this.state.line = {
        id: false,
        product_id: null,
        product_name: "",
        lot_id: null,
        lot_name: "",
        package_id: null,
        package_name: "",
        location_id: null,
        location_name: "",
        quantity_before: 0,
        quantity_counted: 0,
        note: "",
      };
    }
    this.state.view = "DetailInventoryLine";
  }
  async Setquantity(id){
    console.log(id)
    this.state.selectedLine = id.id
    if (!id || typeof id !== "object") {
      console.error("Invalid id:", id);
      return;
    }

    if (id.state === "pending") {
        id.quantity_counted = id.quantity_before;
        id.state = "counting";
    } else if (id.state === "counting") {
        id.state = "pending";
        id.quantity_counted = 0;
    } 

      const get_data = await this.orm.call(
          "smartbiz.inventory",
          "save_order",
          [,this.state.selectedOrder, id],
          {}
      );

      if (get_data && get_data.lines) {
          this.state.lines = get_data.lines;
      } else {
          console.error("Invalid response from save_order:", get_data);
      }
    
  }
  scrollToSelectedMove() {
    const selectedElement = document.querySelector(`[data-id="${this.state.selectedLine}"]`);
    if (selectedElement) {
        selectedElement.scrollIntoView({
            behavior: "smooth", // Hiệu ứng cuộn mượt
            block: "center",    // Căn giữa màn hình
        });
    }
  }
  getClass(line) {
    // console.log(line)
    let cl = " ";
    if (line.state === "counting") {
      if (line.quantity_counted === line.quantity_before) {
        cl += " bg-green";
      } else if (line.quantity_counted < line.quantity_before) {
        cl += " bg-yellow";
      } else if (line.quantity_counted > line.quantity_before) {
        cl += " bg-red";
      } else {
        cl += "";
      }
    }
    this.scrollToSelectedMove();
    return cl;
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
