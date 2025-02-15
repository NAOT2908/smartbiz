/** @odoo-module **/
import { registry } from "@web/core/registry";
import { Component, EventBus, onPatched, onWillStart, useState, useSubEnv, xml } from "@odoo/owl";
import { useService, useBus, useHistory } from "@web/core/utils/hooks";
import * as BarcodeScanner from "@web/webclient/barcode/barcode_scanner";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { View } from "@web/views/view";
import { ManualBarcodeScanner } from "../Components/manual_barcode";
import { url } from "@web/core/utils/urls";
import { utils as uiUtils } from "@web/core/ui/ui_service";
import SmartBizBarcodePickingModel from "../Models/barcode_picking";

export class StockQuant extends Component {
  setup() {
    this.rpc = useService("rpc");
    this.notification = useService("notification");
    this.orm = useService("orm");
    this.dialog = useService("dialog");
    this.action = useService("action");
    this.home = useService("home_menu");

    this.state = useState({
      menuVisible: false,
      search: false,
      searchInput: "",
      inventoryData: [],
      data: [],
    });

      this._scrollBehavior = "smooth";
      this.isMobile = uiUtils.isSmall();
      this.barcodeService = useService("barcode");
      useBus(this.barcodeService.bus, "barcode_scanned", (ev) =>
        this.onBarcodeScanned(ev.detail.barcode)
      );
      const services = { rpc: this.rpc, orm: this.orm, notification: this.notification, action: this.action };
          const model = new SmartBizBarcodePickingModel('stock.quant', false, services);
          useSubEnv({ model });
      onWillStart(async () => {
        await this.loadInventoryData();
      });
  }

  async loadInventoryData() {
    try {
    //   const data = await this.orm.searchRead(
    //     "stock.quant",
    //     [
    //       ["quantity", ">", 0],
    //       ["location_id.usage", "=", "internal"],
    //     ],
    //     []
    //   );
    const data = await this.orm.call('stock.quant', 'get_inventory_data', [], {});
      this.state.inventoryData = data;
      this.state.data = data;
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

  handleInput(event) {
    this.state.searchInput = event.target.value;
    this.search();
  }
  search() {
    if (this.state.searchInput !== "") {
      this.state.data = this.filterArrayByString(
        this.state.inventoryData,
        this.state.searchInput
      )
    //   .sort((a, b) =>
    //     b.product_id[1] ? b.product_id[1].localeCompare(a.product_id[1]) : 0
    //   );
    } else {
      this.state.data = this.state.inventoryData
    //   .sort((a, b) =>
    //     a.product_id[1] ? a.product_id[1].localeCompare(b.product_id[1]) : 0
    //   );
    }
  }
  async exit(ev) {
    // if () {
        await this.action.doAction("smartbiz_barcode.smartbiz_barcode_main_menu_action"); // Quay lại nếu có action trước
    // } else {
    //     this.home.toggle(true);
    // }
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
      this.state.data = this.state.inventoryData
    //   .sort((a, b) =>
    //     a.product_id[1] ? a.product_id[1].localeCompare(b.product_id[1]) : 0
    //   );
    }
    // if (!this.state.search) {
    //   this.state.moves = this.env.model.data.moves.sort((a, b) =>
    //     b.product_name.localeCompare(a.product_name)
    //   );
    //   this.state.lines = this.lines;
    // }
  }

  async processBarcode(barcode){
    console.log(this.env.model);
    var barcodeData = await this.env.model.parseBarcodeForInventory(
        barcode,
        false,
        false,
        false
    );
    console.log(barcodeData)
    if (!barcodeData || !barcodeData.match) {
      this.notification.add(`Barcode: ${barcode} không hợp lệ!`, { type: "warning" });
      return;
    }
    if (!barcodeData.record || !barcodeData.record.products) {
        this.notification.add(`Không tìm thấy thông tin của barcode: ${barcode}!`, { type: "warning" });
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

StockQuant.template = "smartbiz_barcode.CustomInventoryViewTemplate";
StockQuant.props = [
  "action?",
  "actionId?",
  "className?",
  "globalState?",
  "resId?",
];

registry.category("actions").add("smartbiz_barcode.StockquantView", StockQuant);
