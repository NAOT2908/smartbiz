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
} from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { COMMANDS } from "@barcodes/barcode_handlers";
import { useService, useBus, useHistory } from "@web/core/utils/hooks";
import * as BarcodeScanner from "@web/webclient/barcode/barcode_scanner";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { View } from "@web/views/view";
import { ManualBarcodeScanner } from "@smartbiz_barcode/Components/manual_barcode";
import { url } from "@web/core/utils/urls";
import { utils as uiUtils } from "@web/core/ui/ui_service";
import {DialogModal} from "@smartbiz/Components/dialogModal";
import { MoveLineEdit,MoveLines,Moves} from "./stockMove.js";
import { EditQuantityModal } from "./EditQuantityModal";
import { Selector, ProductionEntryDialog } from "./Selector";
import { Packages,EditPackage,CreatePackages } from "@smartbiz_barcode/Components/Package";
import SmartBizBarcodePickingModel from "@smartbiz_barcode/Models/barcode_picking";

COMMANDS["O-CMD.MAIN-MENU"] = () => {};
COMMANDS["O-CMD.cancel"] = () => {};

const bus = new EventBus();



export class ProductOrderDetail extends Component {
  static template = "ProductOrderDetail";
  static components = {
    MoveLines,
    Moves,
    DialogModal,
    MoveLineEdit,
    EditQuantityModal,
    Selector,
	ProductionEntryDialog,					  
    Packages,
    EditPackage,
    CreatePackages
  };

  setup() {
    this.rpc = useService("rpc");
    this.notification = useService("notification");
    this.orm = useService("orm");
    this.dialog = useService("dialog");
    this.action = useService("action");
    this.home = useService("home_menu");
    if (this.props.action.res_model === "mrp.production") {
      this.production_id = this.props.action.context.active_id;
    }
     console.log(this.production_id);

    this.state = useState({
      menuVisible: false,
      detailTitle: "",
      search: false,
      searchInput: "",
      productionOrders: [],
      data: [],
      currentView: "ProductOrderDetail",
      finishedMoves: [],
      activeTab: "info",
      selectedButton: 0,
      demandQuantity: "-",
      selectedProductionOrder: 0,
      selectedMaterial: 0,
      selectedFinished: 0,
      selectedMoveLine: 0,
      materialMoves: [],
      moveLines: [],
      moves: [],
      order: {},
      lots: [],
      locations: [],
      packages: [],
      moveLinesTemp: [],
      detailMoveLine: {},
      products: [],
      quantity: 0,
      showEditQuantityModal: false,
      showSelector: false,
      buttonStatus: {},
      movelineitem: {},
      view: "orderdetails",
      isSelector: true,
      modal:'',
      packageInfo:{},

      //Button status
      showInfo: false,
      showRegisterMaterial: false,
      showRegisterProduct: false,
      showDoneOrder: false,
      showCancelOrder: false,
      showPackMulti: false,
      showPrintLines: false,
      showSave: false,
      finished:false,
      finished_message:'',
      unpacked_move_lines:[],
      //Các biến Dialog
      showDialogModal: false,
      dialogTitle: "",
      dialogAction:"",
      dialogRecords: [],
      dialogFields:[],
      dialogDefault: null,
	  ProductionEntryDialog: false,							   
    });
    this.lines = [];
    this.move = {};
    const services = {
      rpc: this.rpc,
      orm: this.orm,
      notification: this.notification,
      action: this.action,
    };
    this._scrollBehavior = "smooth";
    this.isMobile = uiUtils.isSmall();
    this.barcodeService = useService("barcode");
    useBus(this.barcodeService.bus, "barcode_scanned", (ev) =>
      this.onBarcodeScanned(ev.detail.barcode)
    );
    const model = new SmartBizBarcodePickingModel(
      "mrp.production",
      this.production_id,
      services
    );
    useSubEnv({ model });
    // console.log(model);
    onWillStart(async () => {
      await this.loadData();
    });
  }
  footerClass() {
    var cl = "s_footer";

    if (this.state.order.state === "done"){
        cl += " s_footer_done";
    }

    return cl;
  }
//Các hàm sử lý Package - Start

  showModal(modal,data){
    
    if(data && modal =="editPackage"){
      let cl = this.state.data.finish_packages.find(x=>x.id ==data.id).lines;
      let line = this.state.data.unpacked_move_lines;
      line = [...cl,...line]
      let unpacked_move_lines = []
      console.log({modal,data,line,'state_data':this.state.data})
      for (var l of line) 
      {
        var modified_quantity = l.result_package_id?l.quantity:0;
        var package_name = l.result_package_id?l.result_package_id[1]:''
        var package_id = l.result_package_id?l.result_package_id[0]:false
        unpacked_move_lines.push({
          id:l.id,product_name:l.product_id[1],
          current_quantity:l.quantity,
          modified_quantity:modified_quantity,
          package_name:package_name,
          result_package_id:package_id
        })
      }
      this.state.packageInfo = data
      this.state.unpacked_move_lines = unpacked_move_lines

    }
    if(modal =="createPackages"){
      
    }
    this.state.modal = modal
  }
  async closeModal(modal,data){
    console.log({modal,data})
    if(data && modal =="editPackage")
    {
      let values =  await this.orm.call(
        "mrp.production",
        "update_package",
        [, this.production_id,data],
        {}
      );

      this.updateData(values)
    }
    if(data && modal =="createPackages")
      {
        let values =  await this.orm.call(
          "mrp.production",
          "create_packages",
          [, this.production_id,data],
          {}
        );
        this.updateData(values)
      }
    this.state.modal = ''
  }
// Hiển thị dialog
openDialog(mode) {
  // mode: 'material' | 'finished'
  this.state.entryMode = mode;
  this.state.ProductionEntryDialog = true;
}
closeDialog() {
  // reset
  this.state.ProductionEntryDialog=false;
}



// ★★★ Helper: tạo pack_spec mặc định ★★★
buildDefaultPackSpec() {
  // Có thể tinh chỉnh quy cách đóng gói mặc định ở đây
  const order = this.state.order || {};
  return {
    target: 'finished',             // 'finished' (thành phẩm) hoặc 'raw' (nguyên liệu)
    pack_size: 10,                  // số lượng / gói (mặc định)
    default_package_type_id: false, // có thể điền ID của stock.package.type
    group_by_lot: true,             // gom theo lô, tránh trộn lô trong 1 gói
    allow_remainder: true,          // cho phép gói cuối < pack_size
    skip_if_packed: true,  
	unreserve_raw: true,	// bỏ qua dòng đã có result_package_id
    package_name_prefix: order?.name || 'MO',
    // location_dest_id: false,     // nếu muốn ép đích về 1 location, set ID ở đây
    per_product: {
      // <product_id>: { pack_size: 12, package_type_id: <int>, location_dest_id: <int> }
    },
  };
}

// ★★★ UI action: mở xác nhận và thực thi ★★★
// ★★★ UI action: mở form tham số & thực thi (dùng DialogModal nội bộ) ★★★
async openUnreserveAndPack(prefill = null) {
  this.state.menuVisible = false;

  // defaults từ spec mặc định + prefill (nếu vừa validate fail)
  const defaults = { ...(this.buildDefaultPackSpec?.() || {}), ...(prefill || {}) };
  const order = this.state.order || {};

  // options cho select
  const targetOptions = [
    { id: "finished", name: _t("Thành phẩm") },
    { id: "raw",      name: _t("Nguyên liệu") },
  ];
  const yesNoOptions = [
    { id: true,  name: _t("Có") },
    { id: false, name: _t("Không") },
  ];

  // nạp Package Type & Location để người dùng chọn
  let packageTypeOptions = [];
  try {
    const pts = await this.orm.searchRead("stock.package.type", [], ["name"]);
    packageTypeOptions = (pts || []).map((r) => ({ id: r.id, name: r.name }));
  } catch (e) {
    packageTypeOptions = [];
  }
  const locationOptions = (this.state.locations || []).map((l) => ({
    id: l.id, name: l.display_name || l.name,
  }));

  // cấu hình fields cho DialogModal của bạn
  const fields = [
    { name: "target", label: _t("Đối tượng"), type: "select", required: true, options: targetOptions },
    { name: "pack_size", label: _t("Quy cách/Pack size"), type: "number", required: true },
    { name: "location_dest_id", label: _t("Vị trí đích (ép)"), type: "select", options: locationOptions, dialog: true },
    { name: "package_name_prefix", label: _t("Tiền tố tên kiện"), type: "text" },
    { name: "unreserve_raw", label: _t("Hủy dự trữ nguyên liệu"), type: "select", options: yesNoOptions },

    // nâng cao: per_product (JSON)
    { name: "use_per_product", label: _t("Cấu hình theo từng sản phẩm?"), type: "select",
      options: [{ id: "no", name: _t("Không") }, { id: "yes", name: _t("Có") }] },
    { name: "per_product_json", label: _t("per_product (JSON)"),
      type: "textarea",
      visible_if: { field: "use_per_product", operator: "=", value: "yes" } },
  ];

  // default values (đúng schema DialogModal của bạn)
  const defaultValues = {
    target: defaults.target || "finished",
    pack_size: defaults.pack_size ?? 10,
    location_dest_id: defaults.location_dest_id || "",
    package_name_prefix: defaults.package_name_prefix || order?.name || "MO",
    unreserve_raw: !!defaults.unreserve_raw,

    use_per_product:
      defaults.per_product && Object.keys(defaults.per_product).length ? "yes" : "no",
    per_product_json: defaults.per_product
      ? JSON.stringify(defaults.per_product, null, 2)
      : "{\n  \"<product_id>\": { \"pack_size\": 12, \"package_type_id\": 1, \"location_dest_id\": 5 }\n}",
  };

  // đẩy state để render DialogModal
  this.state.dialogTitle   = _t("Thiết lập đóng gói tự động");
  this.state.dialogAction  = "pack_auto_params";
  this.state.dialogFields  = fields;
  this.state.dialogDefault = defaultValues;
  this.state.dialogRecords = [];         // không dùng ở mode 'fields'
  this.state.showDialogModal = true;     // 👉 mở DialogModal
}


// ★★★ Nhận dữ liệu từ DialogModal của bạn & gọi pack_auto ★★★
onPackSpecDialogClose = async (title, form, action) => {
  // luôn đóng modal
  this.state.showDialogModal = false;

  // người dùng bấm "Hủy"
  if (!form) return;

  // ép kiểu boolean nếu form trả về 'true'/'false' dạng string
  const toBool = (v) => (v === true || v === "true");

  const packSize = Number(form.pack_size || 0);
  if (!packSize || packSize <= 0) {
    this.notification.add(_t("Giá trị Pack size phải > 0."), { type: "danger" });
    // mở lại dialog với dữ liệu người dùng vừa nhập
    return this.openUnreserveAndPack(form);
  }

  const spec = {
    target: form.target || "finished",
    pack_size: packSize,
    default_package_type_id: form.default_package_type_id || false,
    location_dest_id: form.location_dest_id || false,
    package_name_prefix: form.package_name_prefix || undefined,
    unreserve_raw: toBool(form.unreserve_raw),
  };

  // per_product JSON (tùy chọn)
  if (form.use_per_product === "yes") {
    const raw = (form.per_product_json || "").trim();
    if (raw) {
      try {
        spec.per_product = JSON.parse(raw);
      } catch (e) {
        this.notification.add(_t("JSON 'per_product' không hợp lệ. Vui lòng kiểm tra cú pháp."), { type: "danger" });
        return this.openUnreserveAndPack(form);
      }
    } else {
      spec.per_product = {};
    }
  }

  // gọi backend
  await this.doUnreserveAndPack(spec);
}

// ★★★ Gọi server & refresh data ★★★
async doUnreserveAndPack(packSpec) {

    const res = await this.orm.call(
		  "mrp.production",
		  "pack_auto",
		  [, this.production_id, packSpec], // <-- có 1 "lỗ" ở đầu mảng
		  {}
		);
	console.log(res)
    // Sau khi xử lý xong, refresh lại dữ liệu màn hình
    await this.loadData();

    const msg = _t(
      `Đã hủy dự trữ ${res?.unreserved_moves || 0} move; ` +
      `tạo ${res?.created_packages || 0} kiện; ` +
      `gán ${res?.packed_lines || 0} dòng.`
    );
    this.notification.add(msg, { type: "success" });
 
}


//Các hàm sử lý Package - End
  async loadData() {
    try {
      const data = await this.orm.call(
        "mrp.production",
        "get_data",
        [, this.production_id],
        {}
      );
      this.updateData(data);
    } catch (error) {
      console.error("Error loading data:", error);
      this.notification.add("Failed to load inventory data" + error, {
        type: "danger",
      });
    }
  }
  updateData(data){
    this.state.data = data;
    this.state.productionOrders = data.order.find(x => x.id === this.production_id);
    this.state.detailTitle = data?.order[0].name;
    this.state.materialMoves = data.materials;
    this.state.finishedMoves = data.finisheds;
    this.state.moveLinesTemp = data.moveLines;
    this.state.moves = data.moves;
    this.state.products = data.products;
    this.state.order = data?.order[0];
    this.state.lots = data.lots;
    this.state.locations = data.locations;
    this.state.packages = data.packages;
    this.state.finish_packages = data.finish_packages;

    this.updateButton();

  }
  changeTab(tab) { 
      this.state.activeTab = tab;
      this.updateButton();
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
  productionOrderClick(orderId) {
    this.state.finishedMoves = this.state.productionOrders.filter(
      (x) => x.id == orderId
    );
    this.state.currentView = "FinishedMoves";
  }
  handleInput(event) {
    this.state.searchInput = event.target.value;
    this.search();
  }
  search() {
    if (this.state.searchInput !== "") {
      this.state.productionOrders = this.filterArrayByString(
        this.state.data,
        this.state.searchInput
      );
    } else {
      this.state.productionOrders = this.state.data;
    }
  }
  searchClick() {
    this.state.search = this.state.search ? false : true;
    this.state.searchInput = "";
    if (!this.state.search) {
      this.state.productionOrders = this.state.data;
    }
  }
  async exit(ev) {
    if (
      this.state.view === "editMove" ||
      this.state.view === "editMaterial"
    ) {
      // Nếu đang trong chế độ chỉnh sửa, quay lại chế độ hiển thị chi tiết
      this.state.view = "orderdetails";
    } else if (this.state.currentView === "ProductOrderDetail") {
      if (
        this.env.config.breadcrumbs &&
        this.env.config.breadcrumbs.length > 1
      ) {
        this.env.config.historyBack();
      } else {
        // Nếu không có lịch sử điều hướng, quay về màn hình chính
        this.home.toggle(true);
      }
    } else if (this.state.currentView === "FinishedMoves") {
      // Quay lại danh sách chi tiết sản phẩm
      this.state.currentView = "ProductOrderDetail";
    }
    this.updateButton();
  }
  moveLineClick = (id) => {
    this.state.selectedMoveLine = id;
    const line = this.state.moveLines.find((r) => r.id == id);
    // console.log(line)
    if (this.state.view === "editMaterial") {
      const move = this.state.moves.find(
        (r) => r.id == this.state.selectedMaterial
      );
      this.state.quantity = line.quantity;
      this.state.detailMoveLine = {
        id: id,
        move_id: line.move_id,
        product_id: line.product_id,
        product_name: line.product_name,
        location_id: line.location_id,
        location_name: line.location_name,
        location_dest_id: line.location_dest_id,
        location_dest_name: line.location_dest_name,
        product_uom_id: line.product_uom_id,
        product_uom: line.product_uom,
        product_uom_qty: move.product_uom_qty || 0,
        qty_done: line.quantity || 0,
        quantity: line.quantity || 0,
        tracking: line.product_tracking,
        lot_id: line.lot_id,
        lot_name: line.lot_name,
        package_id: line.package_id,
        package_name: line.package_name,
        result_package_id: line.result_package_id,
        result_package_name: line.result_package_name,
      };
    } else if (this.state.view === "editMove") {
      const move = this.state.moves.find(
        (r) => r.id == this.state.selectedFinished
      );
      this.state.quantity = line.quantity;
      this.state.detailMoveLine = {
        id: id,
        move_id: line.move_id,
        product_id: line.product_id,
        product_name: line.product_name,
        location_id: line.location_id,
        location_name: line.location_name,
        location_dest_id: line.location_dest_id,
        location_dest_name: line.location_dest_name,
        product_uom_id: line.product_uom_id,
        product_uom: line.product_uom,
        product_uom_qty: move.product_uom_qty || 0,
        qty_done: line.quantity || 0,
        quantity: line.quantity || 0,
        tracking: line.product_tracking,
        lot_id: line.lot_id,
        lot_name: line.lot_name,
        package_id: line.package_id,
        package_name: line.package_name,
        result_package_id: line.result_package_id,
        result_package_name: line.result_package_name,
      };
    }

    // console.log(this.state.detailMoveLine, this.state.view);
  };
  selectItem = (id) => {
    this.state.selectedMaterial = id;
    // console.log(id )
  };
  materialMoveClick = async (id) => {

    this.state.view = "editMaterial";

    this.state.selectedMaterial = id;
    // console.log(this.state.selectedMaterial);
    this.state.selectedFinished = 0;
    this.state.selectedMoveLine = 0;
    this.state.quantity = 0;
    this.state.moveLines = this.state.moveLinesTemp.filter(
      (r) => r.move_id == id
    );
    const move = this.state.moves.find((r) => r.id == id);
    this.move = move;
    this.state.detailMoveLine = {
      id: false,
      move_id: id,
      product_id: move.product_id,
      product_name: move.product_name,
      location_id: move.location_id,
      location_name: move.location_name,
      location_dest_id: move.location_dest_id,
      location_dest_name: move.location_dest_name,
      product_uom_id: move.product_uom_id,
      product_uom: move.product_uom,
      product_uom_qty: move.product_uom_qty || 0,
      qty_done: move.qty_done || 0,
      quantity: move.quantity || 0,
      tracking: move.product_tracking,
      lot_id: null,
      lot_name: "",
      package_id: null,
      package_name: "",
      result_package_id: null,
      result_package_name: "",
    };
    this.updateButton();
  };
  finishedMoveClick = async (id) => {
    this.state.view = "editMove";
    
    this.state.selectedFinished = id;
    this.state.selectedMaterial = 0;
    this.state.selectedMoveLine = 0;
    this.state.quantity = 0;
    this.state.selectedButton = 0;
    this.state.moveLines = this.state.moveLinesTemp.filter(
      (r) => r.move_id == id
    );
    const move = this.state.moves.find((r) => r.id == id);
    this.move = move;
    if(!this.move.lot_id ){
      const lotdata = await this.orm.call(
        "mrp.production",
        "create_lot",
        [
          ,
          this.production_id,
          move.product_id,
          this.state.productionOrders.company_id[0],
          this.state.productionOrders.lot_name
            ? this.state.productionOrders.lot_name
            : this.state.productionOrders.lot_producing_id[1],
        ],
        {}
      );
      this.updateData(lotdata)
      this.state.lots = lotdata.lots
      this.move.lot_id = lotdata.lot_id
      this.move.lot_name = lotdata.lot_name
  
    }
    const order = this.state.productionOrders;
    // console.log(order,move,this.state.moveLines)
    this.state.detailMoveLine = {
      id: false,
      move_id: id,
      product_id: move.product_id,
      product_name: move.product_name,
      location_id: move.location_id,
      location_name: move.location_name,
      location_dest_id: move.location_dest_id,
      location_dest_name: move.location_dest_name,
      product_uom_id: move.product_uom_id,
      product_uom: move.product_uom,
      product_uom_qty: move.product_uom_qty || 0,
      qty_done: move.qty_done || 0,
      quantity: move.quantity || 0,
      tracking: move.product_tracking,
      lot_id:this.move.lot_id,
      lot_name: this.move.lot_name,
      package_id: null,
      package_name: "",
      result_package_id: null,
      result_package_name: "",
    };
  };
  deleteMoveLine = async (id) => {
    const deletedata = await this.orm.call(
      "mrp.production",
      "delete_move_line",
      [, this.production_id, id],
      {}
    );
    this.state.materialMoves = deletedata.materials;
    this.state.finishedMoves = deletedata.finisheds;
    this.state.moveLinesTemp = deletedata.moveLines;

    if (this.state.view === "editMaterial") {
      this.state.moveLines = this.state.moveLinesTemp.filter(
        (r) => r.move_id == this.state.selectedMaterial
      );
    } else if (this.state.view === "editMove") {
      this.state.moveLines = this.state.moveLinesTemp.filter(
        (r) => r.move_id == this.state.selectedFinished
      );
    }
    this.resetDetailMoveLine()
    this.updateData(deletedata)
  };
  saveOrder = async () => {
    try {
      console.log(this.state.detailMoveLine);
      if (!this.state.detailMoveLine.product_id) {
        alert("Sản phẩm không hợp lệ, vui lòng kiểm tra lại.");
        return;
      }

      const data = {
        production_id: this.production_id,
        method: "save_order",
        data: this.state.detailMoveLine,
      };
      await this.checkLot(data);
    } catch (error) {
      console.error("Lỗi khi lưu đơn hàng:", error);
      alert("Đã xảy ra lỗi trong quá trình lưu. Vui lòng thử lại.");
    }
    this.resetDetailMoveLine()
  };
  createLot = async () => {
    const lotdata = await this.orm.call(
      "mrp.production",
      "create_lot",
      [
        ,
        this.production_id,
        this.state.detailMoveLine.product_id,
        this.state.productionOrders.company_id[0],
        this.state.productionOrders.lot_producing_id
          ? this.state.productionOrders.lot_producing_id[1]
          : false,
      ],
      {}
    );
    this.state.lots = lotdata.lots
    this.state.moves = lotdata.moves
    this.state.detailMoveLine.lot_id = lotdata.lot_id;
    this.state.detailMoveLine.lot_name = lotdata.lot_name;
    this.updateData(lotdata);
    // console.log(lotdata);
  };
  print = async (id) => {
    //console.log(id)
    const printdata = await this.orm.call(
      "mrp.production",
      "print_move_line",
      [
        ,
        this.production_id,
        id,
        "SB1"
      ],
      {}
    );
    console.log("ok :", printdata);
  };
  print_lines = async () => {
    if (this.state.view === "editMaterial") {
      this.state.moveLines = this.state.moveLinesTemp.filter(
        (r) => r.move_id == this.state.selectedMaterial
      );
    } else if (this.state.view === "editMove") {
      this.state.moveLines = this.state.moveLinesTemp.filter(
        (r) => r.move_id == this.state.selectedFinished
      );
    }
    //console.log('moveLines',this.state.moveLines)
    for (let item of this.state.moveLines){
      //console.log(item)
      const printdata = await this.orm.call(
        "mrp.production",
        "print_move_line",
        [
          ,
          this.production_id,
          item,
          "SB2"
        ],
        {}
      );
      // console.log("oke nhiều :", printdata);
    }
    
    
    
  };
  packMoveLine = async () => {
    await this.checkLot({
      production_id: this.production_id,
      method: "pack_move_line",
      data: this.state.detailMoveLine,
    });
    
    // await this.loadData();
    this.resetDetailMoveLine()
  };
  validate = () => {
    const params = {
      title: _t("Xác nhận đơn"),
      body: _t("Bạn có chắc chắn muốn hoàn thành."),
      confirm: async () => {
        const validate = await this.orm.call(
          "mrp.production",
          "action_finish_actual",
          [this.production_id],
          {}
        );
        this.updateData(validate.data)
        console.log(validate, "xác nhận");
        if (validate.action.type =='ir.actions.act_window')
        {
          await this.action.doAction(validate.action); 
        }
        console.log(validate, "xác nhận");
        const message = _t(`Lệnh sản xuất hoàn tất`);
        this.notification.add(message, { type: "success" });
      },
      cancel: () => {},
      confirmLabel: _t("Có, xác nhận."),
      cancelLabel: _t("Hủy bỏ"),
    };
    this.dialog.add(ConfirmationDialog, params);
  };
  button_post_prepared_lines =() =>{
    const params = {
      title: _t("Xác nhận"),
      body: _t("Bạn có chắc chắn muốn đóng gói các dòng đã chuẩn bị này không?"),
      confirm: async () => {
        const post = await this.orm.call(
          "mrp.production",
          "button_post_prepared_lines",
          [, this.production_id],
          {}
        );
        this.updateData(post)
        // console.log("Đóng gói");
        const message = _t(`Các dòng đã được đóng gói`);
        this.notification.add(message, { type: "success" });
      },
      cancel: () => {},
      confirmLabel: _t("Có, xác nhận."),
      cancelLabel: _t("Hủy bỏ"),
    };
    this.dialog.add(ConfirmationDialog, params);
  }
  cancelOrder = () => {
    const params = {
      title: _t("Xác nhận"),
      body: _t("Bạn có chắc chắn muốn huỷ lệnh sản xuất này không?"),
      confirm: async () => {
        const cancel = await this.orm.call(
          "mrp.production",
          "cancel_order",
          [, this.production_id],
          {}
        );
        // console.log("Hủy đơn");
        const message = _t(`Lệnh sản xuất đã được hủy`);
        this.notification.add(message, { type: "success" });
      },
      cancel: () => {},
      confirmLabel: _t("Có, xác nhận."),
      cancelLabel: _t("Hủy bỏ"),
    };
    this.dialog.add(ConfirmationDialog, params);
  };

  checkLot = async (data) => {
    const { detailMoveLine, lots, view, selectedMaterial, selectedFinished } = this.state;
    const { product_id, lot_id, tracking } = detailMoveLine;
    if (this.state.detailMoveLine.quantity <= 0) 
    {
      alert("Số lượng phải lớn hơn 0!");
      return;
    }
    const callAndUpdate = async () => {
      const result = await this.orm.call(
        "mrp.production",
        data.method,
        [, data.production_id, data.data],
        {}
      );
      this.state.materialMoves = result.materials;
      this.state.finishedMoves = result.finisheds;
      this.state.moveLinesTemp = result.moveLines;
      this.state.order = result?.order[0];
      this.state.moves = result.moves;

      if (view === "editMaterial") {
        this.state.moveLines = this.state.moveLinesTemp.filter(r => r.move_id == selectedMaterial);
      } else if (view === "editMove") {
        this.state.moveLines = this.state.moveLinesTemp.filter(r => r.move_id == selectedFinished);
      }
      this.updateData(result);
    };

    if (tracking === "lot") {
      if (!lot_id) {
        alert("Vui lòng cập nhập số lô cho sản phẩm!");
        return;
      }
      await callAndUpdate();
    }
    else if (tracking === "serial") {
      if (!lot_id) {
        alert("Vui lòng nhập số serial cho sản phẩm!");
        return;
      }

      const existed = this.state.moveLinesTemp?.some(r => r.lot_id === lot_id);
      if (existed) {
        alert("Số serial này đã được sử dụng. Vui lòng nhập số serial khác!");
        return;
      }
      await callAndUpdate();
    }
    else {
      await callAndUpdate();
    }
  };

  showSerial = () => {
    const tracking = this.state.detailMoveLine.tracking;
    return tracking == "lot" || tracking == "serial";
  };

  resetDetailMoveLine = () => {
      this.state.detailMoveLine = {
          ...this.state.detailMoveLine,
          id: false,
          lot_id: null,
          lot_name: "",
          package_id: null,
          package_name: "",
          result_package_id: null,
          result_package_name: "",
          quantity: 0,
          qty_done: 0,
      };
  };
  handleButtonClick = () => {};

  clearSelector() {
    this.records = [];
    this.multiSelect = false;
    this.selectorTitle = "";
    this.state.showSelector = false;
    this.state.isSelector = true;
    this.state.menuVisible = false;
    // this.toggleMenu()
  }
  openSelector = (option) => {
    if (option == 1) {
      //Nguyên liệu đầu vào
      this.records = [];
      this.multiSelect = false;
      this.selectorTitle = "Nguyên liệu đầu vào";
    } else if (option == 2) {
      //Nguyên liệu còn lại
      this.records = this.materialList.filter(
        (x) => x.production_order == this.production_id
      );
      this.multiSelect = false;
      this.selectorTitle = "Nguyên liệu còn lại";
    } else if (option == 3) {
      //Địa điểm nguồn
      this.records = this.state.locations;
      this.multiSelect = false;
      this.selectorTitle = "Chọn vị trí nguồn";
    } else if (option == 4) {
      //Địa điểm đích
      this.records = this.state.locations;
      this.multiSelect = false;
      this.selectorTitle = "Chọn vị trí đích";
    } else if (option == 5) {
      //Chọn số Lot
      this.records = this.state.lots.filter(
        (x) => x.product_id[0] == this.state.detailMoveLine.product_id
      );
      this.multiSelect = false;
      this.selectorTitle = "Chọn số Lô/Sê-ri";
    } else if (option == 6) {
      //Chọn gói đích
      this.records = this.state.packages;
      this.multiSelect = false;
      this.selectorTitle = "Chọn kiện đích";
    } else if (option == 7) {
      //Chọn gói nguồn
      this.records = this.state.packages;
      this.multiSelect = false;
      this.selectorTitle = "Chọn kiện nguồn";
    } else if (option == 8) {
      // Đóng pack hàng loạt
      this.records = this.move;
      this.state.isSelector = false;
      this.multiSelect = false;
      this.state.menuVisible = false;
      this.selectorTitle = "Đóng Packages loạt";
    } else if (option == 9) {
      // Chia pack hàng loạt
      this.records = this.move;
      this.state.isSelector = false;
      this.state.menuVisible = false;
      this.multiSelect = false;
      this.selectorTitle = "Chia tách Packages";
    }
    this.state.showSelector = true;
  };
  closeSelector = async (data, title = "") => {
    if (data) {
      if (title == "Nguyên liệu còn lại") {
        // console.log(data);
      } else if (title == "Chọn vị trí nguồn") {
        this.state.detailMoveLine.location_id = data.id;
        this.state.detailMoveLine.location_name =
          data.display_name || data.name;
      } else if (title == "Chọn vị trí đích") {
        this.state.detailMoveLine.location_dest_id = data.id;
        this.state.detailMoveLine.location_dest_name =
          data.display_name || data.name;
      } else if (title == "Chọn số Lô/Sê-ri") {
        this.state.detailMoveLine.lot_id = data.id;
        this.state.detailMoveLine.lot_name = data.display_name || data.name;
      } else if (title == "Chọn kiện đích") {
        this.state.detailMoveLine.result_package_id = data.id;
        this.state.detailMoveLine.result_package_name =
          data.display_name || data.name;
        // console.log(this.state.detailMoveLine.result_package_name);
      } else if (title == "Chọn kiện nguồn") {
        this.state.detailMoveLine.package_id = data.id;
        this.state.detailMoveLine.package_name = data.display_name || data.name;
      } else if (title == "Tạo Lô/Sê-ri") {
        const lotdata = await this.orm.call(
          "mrp.production",
          "create_lot",
          [
            ,
            this.production_id,
            this.state.detailMoveLine.product_id,
            this.state.order.company_id[0],
            this.state.productionOrders.lot_name
              ? this.state.productionOrders.lot_name
              : this.state.productionOrders.lot_producing_id[1],
          ],
          {}
        );
        this.state.lots = lotdata.lots
        this.updateData(lotdata)
      } else if (this.selectorTitle == "Đóng Packages loạt") {
        
        // this.state.detailMoveLine.lot_id = data.id;
        // this.state.detailMoveLine.lot_name = data.display_name || data.name;
        for (var line of data) {
          const line_lot = this.state.lots.find(
            (l) =>
              l.name === line.lot_name && l.product_id[0] == line.product_id
          );

          if (line_lot) {
            line.lot_id = line_lot.id; // Gán đúng ID từ object tìm được
          } else {
            let lotdata = await this.orm.call(
              "mrp.production",
              "create_lot",
              [
                ,
                this.production_id,
                this.state.detailMoveLine.product_id,
                this.state.productionOrders.company_id[0],
                line.lot_name,
              ],
              {}
            );
            console.log(lotdata)
            this.state.lots = lotdata.lots
            this.state.moves = lotdata.moves
            line.lot_id = lotdata.lot_id;
            this.updateData(lotdata)
          }

          // this.state.detailMoveLine = line
          const mrpdata = await this.orm.call(
            "mrp.production",
            "save_order",
            [, this.production_id, line],
            {}
          );
          // console.log(data, mrpdata);
          this.state.materialMoves = mrpdata.materials;
          this.state.finishedMoves = mrpdata.finisheds;
          this.state.moveLinesTemp = mrpdata.moveLines;
          this.updateData(mrpdata)
        }

        if (this.state.view === "editMaterial") {
          this.state.moveLines = this.state.moveLinesTemp.filter(
            (r) => r.move_id == this.state.selectedMaterial
          );
        } else if (this.state.view === "editMove") {
          this.state.moveLines = this.state.moveLinesTemp.filter(
            (r) => r.move_id == this.state.selectedFinished
          );
        }
      } else if (this.selectorTitle == "Chia tách Packages") {
        // console.log(data)
        for (var line of data){
          const mrpdata = await this.orm.call(
            "mrp.production",
            "save_order",
            [, this.production_id, line],
            {}
          );
          // console.log(data, lotdata);
          this.state.materialMoves = mrpdata.materials;
          this.state.finishedMoves = mrpdata.finisheds;
          this.state.moveLinesTemp = mrpdata.moveLines;
          this.updateData(mrpdata)
        }
        
        if (this.state.view === "editMaterial") {
          this.state.moveLines = this.state.moveLinesTemp.filter(
            (r) => r.move_id == this.state.selectedMaterial
          );
        } else if (this.state.view === "editMove") {
          this.state.moveLines = this.state.moveLinesTemp.filter(
            (r) => r.move_id == this.state.selectedFinished
          );
        }
      }
    }

    this.clearSelector();
    this.updateButton();
  };
  resetButtonStatus() {
    this.state.showCancelOrder = false;
    this.state.showDoneOrder = false;
    this.state.showRegisterMaterial = false;
    this.state.showRegisterProduct = false; 
    this.state.showPackMulti = false;
    this.state.showInfo = false;
    this.state.showPrintLines = false;
    this.state.showSave = false;
  }
  updateButton() {
    this.resetButtonStatus();
    if (this.state.view === "orderdetails") {
        if(this.state.order.state == 'done')
        {
            this.state.showInfo = true;
            this.state.finished_message = 'Đã hoàn tất';
        }
        else if(this.state.order.state == 'cancel')
        {
            this.state.showInfo = true;
            this.state.finished_message = 'Đã bị hủy';
        }
        else{
          if (this.state.activeTab === "material") {
            this.state.showRegisterMaterial = true;
          } else if (this.state.activeTab === "finished") {
            this.state.showRegisterProduct = true;  
          } else if (this.state.activeTab === "packaging") {
            this.state.showPackMulti = true;
          } else if (this.state.activeTab === "info") {
            this.state.showCancelOrder = true;
            this.state.showDoneOrder = true;
          }
        }
      
    }
    else if (this.state.view === "editMaterial" || this.state.view === "editMove") {
      if(this.state.detailMoveLine.quantity > 0){
        this.state.showSave = true;
      }
      if(this.state.moveLines.length > 0){
        this.state.showPrintLines = true;
      }
    }
  


    this.state.finished = false;
    this.state.finished_message = '';
    if(this.state.order.state == 'done')
      {
          this.state.finished = true;
          this.state.finished_message = 'Đã hoàn tất';
      }
      else if(this.state.order.state == 'cancel')
      {
          this.state.finished = true;
          this.state.finished_message = 'Đã bị hủy';
      }
    // console.log(this.state.detailMoveLine)
    if (
      this.state.detailMoveLine.tracking == "lot" ||
      this.state.detailMoveLine.tracking == "serial"
    ) {
      this.state.buttonStatus.showLot = true;
    }
    if (
      this.state.detailMoveLine.product_id &&
      this.state.detailMoveLine.location_id &&
      this.state.detailMoveLine.location_dest_id &&
      (!this.state.buttonStatus.showLot || this.state.detailMoveLine.lot_id)
    ) {
      this.state.buttonStatus.save = true;
    }
    if (!this.state.detailMoveLine.lot_id) {
      this.state.buttonStatus.createLot = true;
    }
    if (this.state.buttonStatus.showLot) {
      this.state.buttonStatus.selectLot = true;
    }

    if (
      this.state.buttonStatus.save &&
      !this.state.detailMoveLine.result_package_id
    )
      this.state.buttonStatus.createPackage = true;

    if (
      this.state.buttonStatus.save &&
      (this.state.detailMoveLine.result_package_id ||
        !this.state.buttonStatus.showLot)
    )
      this.state.buttonStatus.print = true;

    if (this.state.order.qty_producing)
      // console.log(this.state.order)
      this.state.buttonStatus.validate = true;
  }

  editQuantityClick = () => {
    this.state.showEditQuantityModal = true;
  };

  closeQuantityModal = () => {
    this.state.showEditQuantityModal = false;
    this.updateButton();
  };
  clearResultPackage = () => {
    // console.log(this.state.detailMoveLine)
    this.state.detailMoveLine.result_package_id = false;
    this.state.detailMoveLine.result_package_name = "";
    this.updateButton();
  };
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
      await this.processBarcode(barcode, this.production_id);

      if ("vibrate" in window.navigator) {
        window.navigator.vibrate(100);
      }
    } else {
      const message = _t("Please, Scan again!");
      this.notification.add(message, { type: "warning" });
    }
  }

  scrollToSelectedMove() {
        const selectedElement = document.querySelector(`[data-id="${this.state.selectedMove}"]`);
        if (selectedElement) {
            selectedElement.scrollIntoView({
                behavior: "smooth", // Hiệu ứng cuộn mượt
                block: "center",    // Căn giữa màn hình
            });
        }
    }
  async processBarcode(barcode, production_id) {
    var barcodeData = await this.env.model.parseBarcodeMrp(
      barcode, false, false, false
    );

    // console.log(barcodeData, production_id);
    if (this.state.view === "editMaterial") {
        const line = this.state.moves.find(
            (r) => r.id == this.state.selectedMaterial
        );
        const barcodeProducts = barcodeData.record.products.filter(
            (r) => r.product_id == line.product_id
        );

        console.log(barcodeProducts, line);
        if (barcodeProducts.length > 0) {
            const newMovelineItems = [];

            for (const barcodeProduct of barcodeProducts) {
                // Kiểm tra xem đã có moveLine với package_id trùng chưa
                let existingMoveline = this.state.moveLinesTemp.find(
                    (r) => r.move_id == this.state.selectedMaterial &&
                           r.product_id == line.product_id &&
                           r.package_id == barcodeData.record.id
                );

                if (existingMoveline) {
                    // Nếu đã tồn tại, chỉ cần cập nhật số lượng
                    existingMoveline.qty_done = existingMoveline.quantity;
                    existingMoveline.quantity = existingMoveline.quantity;

                    const savedata = await this.orm.call(
                        "mrp.production",
                        "save_order",
                        [, production_id, existingMoveline],
                        {}
                    );
                    this.updateData(savedata);
                } else {
                    // Nếu chưa tồn tại, tạo mới moveline
                    const movelineitem = {
                        id: false,
                        move_id: this.state.selectedMaterial,
                        product_id: line?.product_id || null,
                        product_name: line?.product_name || "",
                        location_id: barcodeProduct?.location_id || null,
                        location_name: barcodeProduct?.location_name || "",
                        location_dest_id: line?.location_dest_id || null,
                        location_dest_name: line?.location_dest_name || "",
                        product_uom_id: line?.product_uom_id || null,
                        product_uom: line?.product_uom || "",
                        product_uom_qty: line?.product_uom_qty || 0,
                        qty_done: barcodeProduct.quantity,
                        tracking: line?.product_tracking || "none",
                        quantity: barcodeProduct.quantity || 0,
                        lot_id: barcodeProduct.lot_id || null,
                        lot_name: barcodeProduct.lot_name || "",
                        package_id: barcodeData.record.id || null,
                        package_name: barcodeData.record.name || "",
                        result_package_id: line?.result_package_id || null,
                        result_package_name: line?.result_package_name || "",
                    };

                    // Kiểm tra số lượng và cập nhật package
                    if (barcodeProducts.length <= 1) {
                        if (line?.product_uom_qty >= barcodeProduct.quantity) {
                            movelineitem.result_package_id = barcodeData.record.id || null;
                            movelineitem.result_package_name = barcodeData.record.name || "";
                            movelineitem.qty_done = barcodeProduct.quantity;
                        } else {
                            movelineitem.qty_done = line?.product_uom_qty || 0;
                            movelineitem.quantity = line?.product_uom_qty || 0;
                            movelineitem.result_package_id = null;
                            movelineitem.result_package_name = "";
                        }
                    }

                    newMovelineItems.push(movelineitem);

                    // Gọi API để lưu moveline mới
                    const savedata = await this.orm.call(
                        "mrp.production",
                        "save_order",
                        [, production_id, movelineitem],
                        {}
                    );
                    this.updateData(savedata);
                }
            }

            // Cập nhật moveLines hiển thị
            this.state.moveLines = this.state.moveLinesTemp.filter(
                (r) => r.move_id == this.state.selectedMaterial
            );
        } else {
            console.error("Không tìm thấy sản phẩm phù hợp trong barcodeData.");
        }
    }
    if (this.state.view === 'orderdetails' && this.state.activeTab === 'material') {
      console.log("Barcode Data:", barcodeData);

      const products = barcodeData?.record?.products || [];
      if (!products.length) {
          console.error("Không tìm thấy sản phẩm phù hợp trong barcodeData.");
          return;
      }

      for (const barcodeProduct of products) {
          if (!barcodeProduct?.product_id) {
              console.warn("Barcode product không hợp lệ:", barcodeProduct);
              continue;
          }

          let line = this.state.moves.find(
              r => r.product_id == barcodeProduct.product_id
          );

          if (line) {
              let existingMoveline = this.state.moveLinesTemp.find(
                  r =>
                      r.move_id == line.id &&
                      r.product_id == line.product_id &&
                      r.package_id == barcodeData.record.id
              );

              if (existingMoveline) {
                  existingMoveline.qty_done = existingMoveline.quantity;
                  existingMoveline.quantity = existingMoveline.quantity;

                  const savedata = await this.orm.call(
                      "mrp.production",
                      "save_order",
                      [, production_id, existingMoveline],
                      {}
                  );

                  this.updateData(savedata);

              } else {
                  const movelineitem = {
                      id: false,
                      move_id: line.id,
                      product_id: line.product_id,
                      product_name: line.product_name || "",
                      location_id: barcodeProduct.location_id || null,
                      location_name: barcodeProduct.location_name || "",
                      location_dest_id: line.location_dest_id || null,
                      location_dest_name: line.location_dest_name || "",
                      product_uom_id: line.product_uom_id || null,
                      product_uom: line.product_uom || "",
                      product_uom_qty: line.product_uom_qty || 0,
                      qty_done: barcodeProduct.quantity,
                      tracking: line.product_tracking || "none",
                      quantity: barcodeProduct.quantity || 0,
                      lot_id: barcodeProduct.lot_id || null,
                      lot_name: barcodeProduct.lot_name || "",
                      package_id: barcodeData.record.id || null,
                      package_name: barcodeData.record.name || "",
                      result_package_id: line.result_package_id || null,
                      result_package_name: line.result_package_name || "",
                  };

                  const savedata = await this.orm.call(
                      "mrp.production",
                      "save_order",
                      [, production_id, movelineitem],
                      {}
                  );

                  this.updateData(savedata);
              }

          } else {
              const movelineitem = {
                  id: false,
                  move_id: null,
                  product_id: barcodeProduct.product_id,
                  product_name: barcodeProduct.product_name || "",
                  location_id: barcodeProduct.location_id || null,
                  location_name: barcodeProduct.location_name || "",
                  location_dest_id: null, 
                  location_dest_name: "",
                  product_uom_id: barcodeProduct.product_uom_id,
                  product_uom: barcodeProduct.product_uom || "",
                  product_uom_qty: barcodeProduct.quantity || 0,
                  qty_done: barcodeProduct.quantity,
                  tracking: barcodeProduct.tracking || "none",
                  quantity: barcodeProduct.quantity || 0,
                  lot_id: barcodeProduct.lot_id || null,
                  lot_name: barcodeProduct.lot_name || "",
                  package_id: barcodeData.record.id || null,
                  package_name: barcodeData.record.name || "",
                  result_package_id: null,
                  result_package_name: "",
              };

              const savedata = await this.orm.call(
                  "mrp.production",
                  "save_raw_order",
                  [, production_id, movelineitem],
                  {}
              );

              this.updateData(savedata);
          }
      }

      this.state.moveLines = this.state.moveLinesTemp.filter(
          r => r.move_id == this.state.selectedMaterial
      );
    }
    this.updateButton();
}

}

registry
  .category("actions")
  .add("smartbiz_barcode_production.PopView", ProductOrderDetail);
