/** @odoo-module **/
import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";
import { COMMANDS } from "@barcodes/barcode_handlers";
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
import { session } from "@web/session";
import { serializeDate, today } from "@web/core/l10n/dates";

class DetailInventoryLine extends Component {
  static template = "DetailInventoryLine";
  static props = ["line", "closeEdit", "deleteItem"];
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

  createLot() {
    const data = this.orm.call('smartbiz.inventory', 'create_lot', [,this.state.line.product_id,lot_name], {});
    console.log(data);
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
    this.userService = useService("user");
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
      inventoryLine: [],
      data: [],
      view: "AdjustmentInventory",
      lines: [],
      line: {},
      title: "",
      isLoading: false,
      selectedOrder: null,
      status: "X",
      selectedLine: null,
      activeTab: "Counting",
      image: null,
      currentLocation : null,
      showEditLine: false,
      currentPage: 1,
      itemsPerPage: 20,
      totalOrders: 0,
      rangeInput: '1-20',
      pageStep: 20,
    });
    //  this.state.rangeInput = `${this.startIndex}-${this.endIndex}`;

    this.stateMapping = {
      pending: "X",
      counting: "V",
      done: "O",
    };
    this.statusOrder = {
      in_progress: "Sẵn sàng",
      cancel: "Hủy",
      done: "Hoàn thành",
      draft: "Nháp",
    };
    console.log("Current user ID:", this.userService)
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
      user: this.userService,
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
      this.state.isLoading = true;
      const offset = (this.state.currentPage - 1) * this.state.itemsPerPage;
      const limit = this.state.itemsPerPage;
      const data = await this.orm.call(
        "smartbiz.inventory",
        "get_order",
        [,],
        { offset: offset, limit: limit }
      );
      this.state.inventoryData = data.orders;
      this.state.data = data.orders;
      this.state.totalOrders = data.total_orders; 
      console.log(data);
    } catch (error) {
      console.error("Error loading data:", error);
      this.notification.add("Failed to load inventory data", {
        type: "danger",
      });
    }
    finally {
        this.state.isLoading = false; // Tắt cờ loading dù thành công hay thất bại
    }
  }

  onRangeChange() {
    const match = this.state.rangeInput.match(/^(\d+)\s*-\s*(\d+)$/);
    if (!match) return;

    let start = parseInt(match[1], 10);
    let end = parseInt(match[2], 10);

    // Không để start nhỏ hơn 1
    if (start < 1) start = 1;

    // Không cho end vượt quá tổng số dữ liệu
    if (end > this.state.totalOrders) end = this.state.totalOrders;

    // Nếu end nhỏ hơn start thì sai logic
    if (start > end) {
      this.notification.add("Khoảng nhập không hợp lệ (bắt đầu lớn hơn kết thúc)", { type: "warning" });
      return;
    }

    this.state.pageStep = end - start + 1;
    this.state.rangeInput = `${start}-${end}`; // Cập nhật lại nếu có thay đổi
    this.loadInventoryDataFromRange(start, end);
  }

  nextPage() {
    const match = this.state.rangeInput.match(/^(\d+)\s*-\s*(\d+)$/);
    if (!match) return;

    const start = parseInt(match[1], 10);
    const end = parseInt(match[2], 10);
    const step = this.state.pageStep; // luôn dùng step này, không tự tính lại

    let newStart = end + 1;
    let newEnd = end + step;

    if (newStart > this.state.totalOrders) return;

    if (newEnd > this.state.totalOrders) {
      newEnd = this.state.totalOrders;
    }

    this.state.rangeInput = `${newStart}-${newEnd}`;
    this.loadInventoryDataFromRange(newStart, newEnd);
  }
  previousPage() {
    const match = this.state.rangeInput.match(/^(\d+)\s*-\s*(\d+)$/);
    if (!match) return;

    const start = parseInt(match[1], 10);
    const step = this.state.pageStep;

    let newStart = start - step;
    if (newStart < 1) newStart = 1;

    let newEnd = newStart + step - 1;
    if (newEnd > this.state.totalOrders) {
      newEnd = this.state.totalOrders;
    }

    this.state.rangeInput = `${newStart}-${newEnd}`;
    this.loadInventoryDataFromRange(newStart, newEnd);
  }
  loadInventoryDataFromRange(start, end) {
    const offset = start - 1;
    const limit = end - start + 1;

    this.state.itemsPerPage = limit;
    this.state.currentPage = Math.floor(offset / limit) + 1;

    this.loadInventoryData();
  }



  changeTab(tabName) {
    this.state.activeTab = tabName;
    this.updateFilteredLines();
  }
  updateFilteredLines() {
    if (this.state.activeTab === "Counting") {
        this.state.lines = this.state.inventoryLine.filter(line => line.state !== "done");
    } else if (this.state.activeTab === "Done") {
        this.state.lines = this.state.inventoryLine.filter(line => line.state === "done");
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
      if(this.state.view === "AdjustmentInventory") {
      
        this.state.data = this.filterArrayByString(
          this.state.inventoryData,
          this.state.search
        );
      } else if(this.state.view === "DetailInventory") {
     
        this.state.lines = this.filterArrayByString(
          this.state.inventoryLine,
          this.state.search
        );
      }
    } else {
      if (this.state.view === "AdjustmentInventory") {
        this.state.data = [...this.state.inventoryData];  
      }
      if (this.state.view === "DetailInventory") {
          this.state.lines = [...this.state.inventoryLine];
          this.updateFilteredLines();
      }
    }
  }
  async exit(ev) {
    if (this.state.view === "DetailInventory") {
      this.state.view = "AdjustmentInventory";
      this.resetData();
    } else if (this.state.view === "AdjustmentInventory") {
      await this.action.doAction(
        "smartbiz_barcode.smartbiz_barcode_main_menu_action"
      );
    } else if (this.state.view === "DetailInventoryLine") {
      this.state.view = "DetailInventory";
    }
  }

  resetData() {
    this.state.currentLocation = null;
    this.state.title = "";
    this.state.selectedLine = null;
    this.state.selectedOrder = null;
    this.state.lines = []
  }
  async closeEdit(data) {
    // console.log(data);
    if (data) {
      data.state = "counting"
      const get_data = await this.orm.call(
        "smartbiz.inventory",
        "save_order",
        [, this.state.selectedOrder, data],
        {}
      );
      console.log(get_data)
      // this.state.data = get_data.orders;
      // this.state.inventoryLine = get_data.lines
      // this.state.lines = get_data.lines;
      this.updatedata(get_data);
      this.updateFilteredLines();
    }
    this.state.showEditLine = false;
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

  async selectOrder(id) {
    this.state.view = "DetailInventory";
    this.state.selectedOrder = id;
    console.log(id)
    const get_data = await this.orm.call(
      "smartbiz.inventory",
      "get_data",
      [, [id]],
      {}
    );
    this.updatedata(get_data);
    // console.log(get_data)
    this.state.title = get_data.inventory.name

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
      this.state.line = this.state.lines.find((line) => line.id === id );
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
        quantity: 0,
        quantity_counted: 0,
        note: "",
      };
    }
    this.state.showEditLine = true;
  }
  
  async deleteItem(id) {
    const params = {
      title: _t("Xác nhận đơn"),
      body: _t("Bạn có chắc chắn muốn xóa dòng kiểm kê này?."),
      confirm: async () => {
        const get_data = await this.orm.call(
          "smartbiz.inventory",
          "delete_inventory_line",
          [,this.state.selectedOrder, id],
          {}
        );
        this.state.inventoryLine = get_data.lines
        this.state.lines = get_data.lines;
        this.updateFilteredLines();
        this.closeEdit(false)
      },
      cancel: () => { },
      confirmLabel: _t("Có, xác nhận."),
      cancelLabel: _t("Hủy bỏ"),
    };
    this.dialog.add(ConfirmationDialog, params);  
  }
  async printLine(id) {
    const get_data = await this.orm.call(
      "smartbiz.inventory",
      "print_inventory_line",
      [,this.state.selectedOrder, id],
      {}
    );
    this.state.inventoryLine = get_data.lines
        this.state.lines = get_data.lines;
        this.updateFilteredLines();
    
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
      if (Number(line.quantity_counted) == Number(line.quantity)) {
        cl += " bg-green ";
      } else if (Number(line.quantity_counted) < Number(line.quantity)) {
        cl += " bg-yellow ";
      } else if (Number(line.quantity_counted) > Number(line.quantity)) {
        cl += " bg-red ";
      } else {
        cl += " ";
      }
    } 
    if(line.state == "done") {
      cl += " bg-green ";
    }
    if (line.id == this.state.selectedLine) {
      cl += "selected";
      this.scrollToSelectedMove();
    }
    return cl;
  }
  selectLine(id) {
    this.state.selectedLine = id;
    // console.log(id)
  }

  async validate() {
    let apply = this.state.lines.filter(l => l.state === 'counting');
    // console.log(apply)
    const get_data = await this.orm.call(
      "smartbiz.inventory",
      "apply_inventory",
      [,this.state.selectedOrder, apply],
      {}
    );
    this.updatedata(get_data);
    // console.log(get_data)
  }
  updatedata(data){
    this.state.inventoryLine = data.lines
    this.state.lines = data.lines;
    this.updateFilteredLines();
  }

  async Setquantity(id){
    // console.log(id)
    this.state.selectedLine = id.id
    if (!id || typeof id !== "object") {
      console.error("Invalid id:", id);
      return;
    }

    if (id.state === "pending") {
        id.quantity_counted = id.quantity;
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
          this.updatedata(get_data);

      } else {
          console.error("Invalid response from save_order:", get_data);
      }
    
  }

  getLocationClass(item) {
    return item.location_id === this.state.currentLocation?.id ? 'highlight-location' : '';
}
  async processBarcode(barcode) {
    console.log(this.env.model);
    var barcodeData = await this.orm.call('smartbiz.inventory', 'get_inventory_barcode_data',
      [,barcode, false, false]
    );
    console.log(barcodeData);
    if (!barcodeData || !barcodeData.match) {
      this.notification.add(`Barcode: ${barcode} không hợp lệ!`, {
        type: "warning",
      });
      return;
    }
    if (this.state.view == "DetailInventory") {
      if (barcodeData.barcodeType === "locations") {
          // Lưu vị trí hiện tại vào state
          this.state.currentLocation = {
              id: barcodeData.record.id,
              display_name: barcodeData.record.display_name
          };
          this.notification.add(`Đã chọn vị trí: ${barcodeData.record.display_name}`, { type: "info" });
          console.log(this.state.currentLocation)
      }
  
      if (this.state.currentLocation) {
          if (barcodeData.barcodeType === "packages") {
            this.state.selectedLine = this.state.lines.find((line) => line.package_id === barcodeData.record.id)?.id;
              // Kiểm tra xem mã vạch có thuộc đúng vị trí đã chọn không
              if (barcodeData.record.location && barcodeData.record.location === this.state.currentLocation.id) {
                  const response = await this.orm.call(
                      "smartbiz.inventory",
                      "process_barcode_scan",
                      [, this.state.selectedOrder, barcodeData],
                      {}
                  );
                  this.updatedata(response);
              } else {
                  const message = _t(`Mã gói: ${barcodeData.barcode} không nằm ở vị trí ${this.state.currentLocation.display_name}!`);
                  this.notification.add(message, { type: "warning" });
              }
          }
          else if (barcodeData.barcodeType === "products"){
            let line = this.state.lines.find((line) => line.product_id === barcodeData.record.id)?.id;
            if (line) {
              this.state.selectedLine = line;
            }
            const message = _t(`Đợi chút đang làm!`);
            this.notification.add(message, { type: "warning" });
          }
          else if (barcodeData.barcodeType === "lots"){
            this.state.selectedLine = this.state.lines.find((line) => line.lot_id === barcodeData.record.id)?.id;
              // Kiểm tra xem mã vạch có thuộc đúng vị trí đã chọn không
              if (barcodeData.record.location_id[0] && barcodeData.record.location_id[0] === this.state.currentLocation.id) {
                  const response = await this.orm.call(
                      "smartbiz.inventory",
                      "process_barcode_scan",
                      [, this.state.selectedOrder, barcodeData],
                      {}
                  );
                  console.log(response)
                  this.updatedata(response);
              } else {
                  const message = _t(`Số lô: ${barcodeData.barcode} không nằm ở vị trí ${this.state.currentLocation.display_name}!`);
                  this.notification.add(message, { type: "warning" });
              }
              
          }
      } else {
          if (barcodeData.barcodeType === "products"){
            let line = this.state.lines.find((line) => line.product_id === barcodeData.record.id);
            console.log(line)
            if (line) {
              this.state.selectedLine = line.id;
            }
            else {
              const message = _t(`Không tìm thấy sản phẩm!`);
              this.notification.add(message, { type: "warning" });
            }
          }
          else if (barcodeData.barcodeType === "lots"){
              if(this.state.selectedLine){
                let line = this.state.lines.find((line) => line.product_id === barcodeData.record.product_id[0]);
                if (line) {
                  this.state.selectedLine = line.id;
                } else {
                  const message = _t(`Không tìm thấy thông tin Lots/Sê-ri!`);
                  this.notification.add(message, { type: "warning" });
                }
              }
        } else {
          this.notification.add(_t("Bạn cần quét vị trí trước!"), { type: "warning" });
        }
      }
    }
  }
}

registry
  .category("actions")
  .add("smartbiz_inventory.AdjustmentInventory", AdjustmentInventory);
