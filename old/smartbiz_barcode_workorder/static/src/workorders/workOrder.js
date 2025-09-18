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
  onWillUnmount
} from "@odoo/owl";
import { useService, useBus, useHistory } from "@web/core/utils/hooks";
import * as BarcodeScanner from "@web/webclient/barcode/barcode_scanner";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { View } from "@web/views/view";
import { ManualBarcodeScanner } from "@smartbiz_barcode/Components/manual_barcode";
import { url } from "@web/core/utils/urls";
import { utils as uiUtils } from "@web/core/ui/ui_service";
import { KeyPads } from "@smartbiz_barcode/Components/keypads";
import { DialogModal } from "@smartbiz/Components/dialogModal";
import { useFileViewer } from "@web/core/file_viewer/file_viewer_hook";
import { patch } from "@web/core/utils/patch";

import SmartBizBarcodePickingModel from "@smartbiz_barcode/Models/barcode_picking";

// Lets `barcodeGenericHandlers` knows those commands exist so it doesn't warn when scanned.
COMMANDS["O-CMD.MAIN-MENU"] = () => {};
COMMANDS["O-CMD.cancel"] = () => {};

const bus = new EventBus();

const { DateTime } = luxon; // Thư viện Luxon để xử lý thời gian

/* ───────── helpers ───────── */
function utcToLocalInput(utcString, tz) {
    // utcString: "YYYY-MM-DD HH:mm:ss" (từ Odoo) hoặc ISO
    return DateTime
        .fromISO(utcString.replace(" ", "T"), { zone: "utc" })   // coi là UTC
        .setZone(tz)                                             // đổi sang TZ người dùng
        .toFormat("yyyy-LL-dd'T'HH:mm");                         // cho <input>
}

function localInputToUtc(localString, tz) {
    // localString: "YYYY-MM-DDTHH:mm" (người dùng nhập)
    return DateTime
        .fromFormat(localString, "yyyy-LL-dd'T'HH:mm", { zone: tz })
        .toUTC()
        .toFormat("yyyy-LL-dd HH:mm:ss");                        // trả về cho Odoo
}



class WorkOrderList extends Component {
  static template = "WorkOrderList";
  static props = [
      "workOrders",          // danh sách sau khi lọc  (state.workOrders)
      "activeTab",           // 'active' | 'done'
      "selectTab",           // hàm đổi tab
      "selectWorkOrder",     // chọn 1 WO
      "selectedWorkOrder",   // id WO hiện hành
      "stateMapping",        // map state → tiếng Việt
  ];

  setup() {
      this.notification = useService("notification");
  }

  getStateClass(state){
      switch (state){
          case "progress": return "state-progress";
          case "pending" : return "state-pending";
          case "ready"   : return "state-ready";
          case "waiting" : return "state-waiting";
          default        : return "state-default";
      }
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
    "selectedComponent?",
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
    if (component.quantity == component.ok_quantity && component.ng_quantity == 0 || component.quantity == (component.ok_quantity + component.ng_quantity)) {
      cl += " bg-green";
    }
    else if (component.quantity > component.ok_quantity && component.ok_quantity != 0) {
      cl += " bg-yellow";
    }
    else if (component.quantity < component.ok_quantity || component.quantity < (component.ok_quantity + component.ng_quantity)) {
      cl += " bg-red";
    }
    return cl;
  }
}

class ActionDetail extends Component {
  static template = "ActionDetail";
  static props = [
    "component",
    "showModal", 
    "updateQuantity",
    "closeModal",
    "printLabel",
    "showKeypad",
    "activityActions",
    "buttonStatus"
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
      duration: this.props.component.actual_duration || 0,
    });

    this.intervalId = setInterval(() => this.updateTimer(), 1000);
    onWillUnmount(() => {
      clearInterval(this.intervalId);
    });
    console.log({buttonStatusSetup:this.props.buttonStatus});
  }
  updateTimer() {
    const { actual_duration, activities } = this.props.component;
    const running = activities.find(a => a.start && !a.finish && a.activity_type === "ok");
    let extraMinutes = 0;
    if (running) {
      const startDT = DateTime.fromFormat(
        running.start,
        "yyyy-LL-dd HH:mm:ss",
        { zone: "utc" }
      );
      const nowUTC = DateTime.utc();
      extraMinutes = nowUTC.diff(startDT, "minutes").minutes;
    }
    // Tổng thời gian
    const total = actual_duration + extraMinutes;
    // Làm tròn xuống 2 chữ số thập phân
    this.state.duration = Math.round(total * 100) / 100;
  }
  activityButtonsStatus(button, activity) {
      const type   = activity.activity_type;  // 'ok' | 'ng' | 'paused' | 'cancel'
      const status = activity.status;         // 'new' | 'started' | 'finished'
      // Với bản ghi paused hoặc cancel: không có nút gì
      if (['paused', 'cancel'].includes(type)) {
          return false;
      }

      // Chỉ còn ok và ng ở đây
      switch (button) {
          case 'edit':
          case 'print':
              // Có thể edit và print cho cả ok và ng, bất kể status
              return ['ok', 'ng'].includes(type);

          case 'delete':
              // Xoá chỉ cho ok/ng ở trạng thái new
              return ['ok', 'ng'].includes(type) && status === 'new';

          case 'cancel':
              // Cancel chỉ cho bản ghi ok khi chưa finish
              return type === 'ok' && status !== 'finished';

          default:
              return false;
      }
  }


  getClass(line) {
    const type     = line.activity_type;   // 'ok' | 'ng' | 'paused' | 'cancel'
    const started  = Boolean(line.start);
    const finished = Boolean(line.finish);

    // 1. Paused → cam
    if (type === 'paused') {
        return 'bg-paused';
    }
    // 2. Cancel → tím nhạt
    if (type === 'cancel') {
        return 'bg-cancel';
    }
    // 3. Chưa làm gì (new) → trắng
    if (!started) {
        return 'bg-new';
    }
    // 4. Đang làm (started nhưng chưa finish) → xanh dương nhạt
    if (started && !finished) {
        return 'bg-inprogress';
    }
    // 5. Hoàn thành
    if (started && finished) {
        if (type === 'ng') {
            return 'bg-finish-ng';
        }
        // OK
        return 'bg-finish-ok';
    }
    // Fallback
    return 'bg-new';
}



}

class ActionDocument extends Component {
  static template = "ActionDocument";
  static props = ["document"];
}

export class WorkOrder extends Component {
  static components = {
    WorkOrderList,
    WorkOrderDetail,
    ComponentList,
    ActionDetail,
    ActionDocument,
    KeyPads,
    DialogModal,
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
    this.userService = useService("user");


    this.selectedActivity = null;
    this.state = useState({
      ordersActive: [],     // NEW
      ordersDone:   [],     // NEW
      activeWOtab: "active",// NEW  ('active' | 'done')
      workOrders: [],
      selectedWorkOrder: {},
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

      buttonStatus:{},

      showkeypad: false,
      view: "",
      menuVisible: false,
      search: false,
      searchInput: "",

      title: "",
      keyPadData: {},
      activeButton: null,
      
      data: [],
      lots: [],
   
      timer: "00:00:00",
      intervalId: null,
      elapsedTime: 0,
      activeTab : "Detail",

      //Biến user và workcenter
      workCenter: false,
      user: false,
      employee: false,

      //Các biến Dialog
      showDialogModal: false,
      dialogTitle: "",
      dialogAction:"",
      dialogRecords: [],
      dialogFields:[],
      dialogDefault: null,
    });
    this.workCenters = []
    this.users = []
    this.employees = []

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

    onWillStart(async () => {
      await this.initData();
    });
    
  }
  /* ---------- HÀM TIỆN ÍCH MỚI ---------- */
  refreshDisplayedWorkOrders(){
    // 1. chọn nguồn theo tab
    const src = this.state.activeWOtab === "active"
              ? this.state.ordersActive
              : this.state.ordersDone;

    // 2. lọc theo Workcenter (nếu có)
    const wcId = this.state.workCenter ? this.state.workCenter.id : null;
    let list = wcId ? src.filter(o => o.workcenter_id === wcId) : src;

    // 3. lọc theo search
    const q = (this.state.searchInput || "").trim().toLowerCase();
    if (q){
        list = list.filter(o =>
            Object.values(o).some(v =>
                String(v).toLowerCase().includes(q)));
    }
    // 4. gán vào biến hiển thị
    this.state.workOrders = list;
  }
  selectTab(tab){
      this.state.activeWOtab = tab;
      this.refreshDisplayedWorkOrders();
  }
  // WorkOrder.js  – thêm vào class WorkOrder
  async fetchLots() {
    const lots = await this.orm.searchRead("stock.lot", [], ["name"]);
    this.state.lots = lots;                 // gán vào state
  }

  // =====================
  // hàm showModal universal
  // =====================
  showModal(title,action='', defaultValues = null){
    const formMap = {
        ok_action:   [{name:'quantity',label:'Số lượng OK',type:'number', required: true}],
        ng_action:   [
            {name:'ng_qty',label:'Số lượng NG',type:'number', required: true},
            {name:'reason_id',label:'Lý do NG', type:'select', options: this.pauseReasons.filter(r => r.type === 'ng'), required: true },
            {name:'note',label:'Ghi chú',type:'textarea'},
        ],
        pause_action:[
            {name:'quantity',label:'Số lượng OK',type:'number', required: true},
            {name:'ng_qty',  label:'Số lượng NG',type:'number'},
            {name: 'reason_id', label:'Lý do tạm dừng', type: 'select', options: this.pauseReasons.filter(r => r.type === 'pause'), required: true,dialog: true},
            {name:'note',    label:'Ghi chú',type:'textarea'},
            
        ],
        edit_productivity: [
            {name:'quantity',label:'Số lượng',type:'number', required: true},     
            {name:'lot_id',  label:'Lô sản xuất', type:'select', options: this.state.lots || []},
            {name:'start',label:'Bắt đầu', type:'datetime-local',readonly: true},
            {name:'finish',label:'Kết thúc', type:'datetime-local',readonly: true},
            {name:'note',    label:'Ghi chú',type:'textarea'},
        ],
    };

    this.state.dialogTitle  = title;
    this.state.dialogAction  = action;

    if (title === 'Chọn trạm sản xuất'){
        this.state.dialogRecords = this.workCenters;
        this.state.dialogFields  = [];
        
    }else{
        this.state.dialogFields  = formMap[action] || [];
        this.state.dialogRecords = [];   // form mode
        this.state.dialogDefault = defaultValues;  
    }
    this.state.showDialogModal = true;
  }

  // ---------------
  // closeModal giữ logic
  closeModal(title,data,action=''){
    if (['ok_action','ng_action','pause_action','start_action'].includes(action) && data){
        this._callHandlePackageScan(action,data);
    }
    else if (action==='edit_productivity' && data){
        this.state.selectedActivity = data.id;
        this.closeActivity(data);
    }
    else if (title==='Chọn trạm sản xuất' && data){
        this.state.workCenter = data; this.updateWorkOrders();
    }
    // reset
    this.state.showDialogModal=false;
    this.state.dialogTitle='';
    this.state.dialogAction='';
    this.state.dialogFields=[];
    this.state.dialogRecords=[];
    
  }
  
  async _callHandlePackageScan(buttonType, vals){
    const args = [
        this.state.selectedWorkOrder.id,      // workorder_id
        this.state.selectedComponent.id,      // component_id
        "",                                   // qr_code rỗng
        this.state.employee.id,               // employee_id
        buttonType,                           // button_type
        false,                                // force
        Number(vals.quantity || 0),           // quantity (OK)
        Number(vals.ng_qty   || 0),           // ng_qty
        vals.note || "" ,                     // note
        vals.reason_id || ""                  // reason_id
    ];
    console.log(args)
    const res = await this.orm.call(
        "mrp.workorder", "handle_package_scan", args, {}
    );
    this.updateSelectedWorkOrder(res);
}

  updateWorkOrders(){
    this.state.title = (this.state.workCenter.name || '-')
    this.refreshDisplayedWorkOrders();
  }
  updateSelectedWorkOrder(data){
    if (data.workOrder && this.state.components){
      this.state.selectedWorkOrder = data.workOrder
      this.state.components = data.components
      this.state.selectedComponent = this.state.components.find(x=>x.id == this.state.selectedComponent?.id)
    }
    this.updateButton()
  }
  async initData() {
 
      let domain  = []
      if(this.state.workCenter)
      {
        domain.push(["workcenter_id","=",this.state.workCenter.id])
      }
      console.log("domain",domain)
      const data = await this.orm.call(
        "mrp.workorder",
        "get_orders",
        [, domain],
        {}
      );
      this.users = data.users
      this.employees = data.employees

      this.state.searchInput = "";
      this.state.data = data;
      this.workCenters = await this.orm.searchRead('mrp.workcenter',[],['name','code']);
      this.state.user = this.users.find(x=>x.id == this.userService.userId)
      this.state.employee = this.employees.find(x=>x.id == this.state.user.employee_id[0]) || this.employees[0]
      this.state.workCenter = this.workCenters.find(x=>x.id == this.state.user.workcenter_id) || false
      console.log({workCenters:this.workCenters,user:this.state.user,workcenter:this.state.workCenter,data})
      if(!this.state.workCenter)
      {
        console.log("OK")
        this.showModal('Chọn trạm sản xuất')
      }
      this.pauseReasons = await this.orm.searchRead(
          'smartbiz_mes.pause_reason', [['active', '=', true]], ['id', 'name', 'type']
      );
      this.state.ordersActive = data.orders_active || [];
      this.state.ordersDone   = data.orders_done   || [];
      this.refreshDisplayedWorkOrders(); // ← thêm dòng này
        this.state.view = "WorkOrders"
      
    //  catch (error) {
    //   //console.error("Error loading data:", error);
    //   this.notification.add("Failed to load inventory data", {
    //     type: "danger",
    //   });
    // }
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


  handleInput(ev){
      this.state.searchInput = ev.target.value;
      this.refreshDisplayedWorkOrders();
  }
  showKeypad = (keyPadTitle, component,type) => {
    var quantity = 0
    var remain_quantity = 0
    if(type == 'ok')
    {
      quantity = component.remain_quantity
      remain_quantity = component.remain_quantity
    }
    else
    {
      quantity = 1
      
    }

    this.state.keyPadData = {
      title:keyPadTitle.title,
      color:keyPadTitle.color,
      quantity,
      remain_quantity,
      type
    };
    this.state.showkeypad = true;
   


  };
 
  closeKeypad = (data,value) => {
    if(value != 'cancel')
    {
      if(data.type == 'ok')
      {
        this.state.selectedComponent.producing_ok_quantity = parseFloat(value)
      }
      else if(data.type == 'ng') 
      {
        this.state.selectedComponent.producing_ng_quantity = parseFloat(value)
      }
    }
    this.state.showkeypad = false;
  };
async search() {
    const query = this.state.searchInput.trim().toLowerCase();
    if (this.state.view === "WorkOrders") {
      if (this.state.workCenter) {
        const datasearch = this.state.data.orders.filter(x=>x.workcenter_id == this.state.workCenter.id);
        if (query) {
          this.state.workOrders = this.filterArrayByString(
            datasearch,
            query
          );
        } else {
          this.state.workOrders = datasearch
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
    if (this.state.view === "WorkOrders") {
      await this.action.doAction(
        "smartbiz_barcode.smartbiz_barcode_main_menu_action"
      );
    } else if (this.state.view === "WorkOrderDetail") {
      let domain  = []
      if(this.state.workCenter)
      {
        domain.push(["workcenter_id","=",this.state.workCenter.id])
      }
      const data = await this.orm.call(
        "mrp.workorder",
        "get_orders",
        [, domain],
        {}
      );
      this.state.data = data
      this.state.view = "WorkOrders";
      // this.stopTimer()
      // this.state.title = ""
      // this.initData();
    } else if (this.state.view === "ActionDetail") {
      this.state.view = "WorkOrderDetail";
      this.state.selectedComponent = null;
      this.state.selectedActivity = null;

    } 
    this.updateWorkOrders()
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
      this.updateSelectedWorkOrder(get_data)
    }
    this.state.view = "ActionDetail";
  }

  async activityActions(action, id) {
    //console.log({action,id})
    if (action == "edit") {
      this.state.selectedActivity = id;
      if (!this.state.lots.length) {          // chỉ gọi khi chưa có
          await this.fetchLots();
      }
      this.showModal("Chỉnh sửa hoạt động", "edit_productivity",id);

    } else if (action == "delete") {
      const params = {
            title: _t("Xác nhận xóa"),
            body: _t("Bạn có chắc chắn muốn xóa không? Thao tác này không thể hoàn tác."),
            confirm: async () => {
              if (id) {
                const get_data = await this.orm.call(
                  "mrp.workorder",
                  "delete_activity",
                  [, this.state.selectedWorkOrder.id, id],
                  {}
                );
                this.updateSelectedWorkOrder(get_data)
              }
              this.state.view = "ActionDetail";
            },
            cancel: () => { },
            confirmLabel: _t("Có, xóa nó"),
            cancelLabel: _t("Hủy bỏ"),
        };
      this.dialog.add(ConfirmationDialog, params);
     
    }else if (action == "cancel") {
      const params = {
            title: _t("Xác nhận hủy"),
            body: _t("Bạn có chắc chắn muốn hủy không? Thao tác này không thể hoàn tác."),
            confirm: async () => {
              if (id) {
                const get_data = await this.orm.call(
                  "mrp.workorder",
                  "cancel_activity",
                  [, this.state.selectedWorkOrder.id, id],
                  {}
                );
                this.updateSelectedWorkOrder(get_data)
              }
              this.state.view = "ActionDetail";
            },
            cancel: () => { },
            confirmLabel: _t("Có, hủy nó"),
            cancelLabel: _t("Hủy bỏ"),
        };
      this.dialog.add(ConfirmationDialog, params);
     
    }
     else if (action == "print") {
      if (id) {
        const get_data = await this.orm.call(
          "mrp.workorder",
          "print_label",
          [, this.state.selectedWorkOrder.id, id],
          {}
        );
        this.updateSelectedWorkOrder(get_data)
      }
      this.state.view = "ActionDetail";
    }
  }
  select(id) {
    // this.state.selectedItem = id;
    // console.log(id);
  }
  updateButton() {
    this.state.buttonStatus = {}
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
    if(this.state.selectedComponent?.activities?.filter(x=>(!x.start && !x.finish) || (x.activity_type == 'paused' && x.start && !x.finish) ).length > 0)
    {
      this.state.buttonStatus.showStart = true;
      this.state.buttonStatus.showOK = false;
      this.state.buttonStatus.showNG = false;
      this.state.buttonStatus.showPause = false;
    }
    else{
      this.state.buttonStatus.showStart = false;
      this.state.buttonStatus.showOK = true;
      this.state.buttonStatus.showNG = true;
      this.state.buttonStatus.showPause = true;
    }
    if (this.state.selectedWorkOrder?.state != 'done'){
      this.state.buttonStatus.deleteActivity = false
    }
    console.log({selectedComponent:this.state.selectedComponent,buttonStatus:this.state.buttonStatus})
  }

  async selectWorkOrder(id) {
    
    const get_data = await this.orm.call(
      "mrp.workorder",
      "get_data",
      [, [id]],
      {}
    );
    this.updateSelectedWorkOrder(get_data)
    this.state.view = "WorkOrderDetail";
  }
  toggleMenu = () => {
    this.state.menuVisible = !this.state.menuVisible;
  };

  // Khi người dùng chọn một thành phần
  selectComponent(component) {
   
    this.state.selectedComponent = component;
    console.log("Selected component:", this.state.selectedComponent);
    this.updateButton();
    
    const pdfUrl = `/web/content?model=mrp.workorder&field=worksheet&id=${this.state.selectedWorkOrder?.id}`;
    //this.state.showPDF = true;
    this.state.document = {
      type: "pdf",
      url: `/web/static/lib/pdfjs/web/viewer.html?file=${encodeURIComponent(
        pdfUrl
      )}`,
    };
    this.state.view = "ActionDetail";
  }


 

  // closePDF = () => {
  //   this.state.showPDF = false;
  // };
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
    if(this.state.selectedWorkOrder.state != "done"){
      const start_workorder = await this.orm.call(
        "mrp.workorder",
        "start_workorder",
        [, this.state.selectedWorkOrder?.id],
        {}
      );
      this.updateSelectedWorkOrder(start_workorder)
      this.startTimer();
    }
    
  }
  async pauseWorkOrder() {
    if(this.state.selectedWorkOrder.state != "done"){
      const pause_workorder = await this.orm.call(
        "mrp.workorder",
        "pause_workorder",
        [, this.state.selectedWorkOrder?.id],
        {}
      );
      this.updateSelectedWorkOrder(pause_workorder)
      this.pauseTimer();
    }
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
        this.updateSelectedWorkOrder(finish_workorder)
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
        "",   
        this.state.employee.id,                                   // qr_code
        "ok_action",                             // button_type
        false,                                   // force (nếu bạn muốn bấm force => true)
        producingOkQuantity                      // quantity
      ],
      {}
    );

    this.updateSelectedWorkOrder(result)
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
        this.state.employee.id,
        "ng_action",       // button_type
        false,             // force
        producingNgQuantity
      ],
      {}
    );

    this.updateSelectedWorkOrder(result)
  }
  async updateQuantity(type, operation) {
    if (type == "ok") {
      if (operation == "+") {
        this.state.selectedComponent.producing_ok_quantity += 1;
      }
      if (operation == "-") {
        this.state.selectedComponent.producing_ok_quantity -= 1;
      }

      let result = await this.orm.call(
        "mrp.workorder",
        "update_component",
        [, "ok", this.state.selectedComponent],
        {}
      );
      this.updateSelectedWorkOrder(result)
    }
    if (type == "ng") {
      if (operation == "+") {
        this.state.selectedComponent.producing_ng_quantity += 1;
      }
      if (operation == "-") {
        this.state.selectedComponent.producing_ng_quantity -= 1;
      }
      let result = await this.orm.call(
        "mrp.workorder",
        "update_component",
        [, "ng", this.state.selectedComponent],
        {}
      );
      this.updateSelectedWorkOrder(result)
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
      await this.processBarcode(barcode);

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

    barcodeData = await this.orm.call(
          'mrp.workcenter', // Model
          'get_barcode_data',      // Method name
          [,barcode,,{'workcenter_id':this.state.workCenter.id}], // Arguments
          {}
      );
    console.log(barcodeData)
    if (barcodeData && barcodeData.match) {
        if (this.state.view === "WorkOrders") {
          console.log("Barcode Data (ScanWorkCenter):", barcodeData);
          if (barcodeData.barcodeType === "employees") {
            this.state.employee = this.employees.find(x=>x.id == barcodeData.record.id);
          }
          if (barcodeData.barcodeType === "workcenters") {
            
            this.state.workCenter = this.workCenters.find(x=>x.id == barcodeData.record.id)

            let domain  = []
            if(this.state.workCenter)
            {
              domain.push(["workcenter_id","=",this.state.workCenter.id])
            }
            const data = await this.orm.call(
              "mrp.workorder",
              "get_orders",
              [, domain],
              {}
            );
            this.state.data = data
            this.updateWorkOrders()
          }
          if (barcodeData.barcodeType === "production_activities") {     
            await this.selectWorkOrder(barcodeData.record.work_order_id[0])     
            this.state.selectedComponent = this.state.components.find(x=>x.id == barcodeData.record.component_id[0])
            this.selectComponent(this.state.selectedComponent)
            
            const data = await this.orm.call(
              "mrp.workorder",
              "handle_package_scan",
              [
                this.state.selectedWorkOrder.id,      // workorder_id
                this.state.selectedComponent.id,      // component_id
                barcode,                              // qr_code rỗng
                this.state.employee.id,               // employee_id
                false,                                // button_type
                false,                                // force
                0,                                    // quantity (OK)
                0,                                    // ng_qty
                "" ,                                  // note
                false                                 // reason_id
              ],
              {}
            );
            this.updateSelectedWorkOrder(data)
          }
        }
        else if (this.state.view === "WorkOrderDetail") {

          if (barcodeData.barcodeType === "employees") {
            this.state.employee = this.employees.find(x=>x.id == barcodeData.record.id);
          }
          
          if (barcodeData.barcodeType === "production_activities") {     
            await this.selectWorkOrder(barcodeData.record.work_order_id[0])     
            this.state.selectedComponent = this.state.components.find(x=>x.id == barcodeData.record.component_id[0])
            this.selectComponent(this.state.selectedComponent)
            console.log({selectedWorkOrder:this.state.selectedWorkOrder,selectedComponent:this.state.selectedComponent})
            const data = await this.orm.call(
              "mrp.workorder",
              "handle_package_scan",
              [
                this.state.selectedWorkOrder.id,      // workorder_id
                this.state.selectedComponent.id,      // component_id
                barcode,                              // qr_code rỗng
                this.state.employee.id,               // employee_id
                false,                                // button_type
                false,                                // force
                0,                                    // quantity (OK)
                0,                                    // ng_qty
                "" ,                                  // note
                false                                 // reason_id
              ],
              {}
            );
            this.updateSelectedWorkOrder(data)
          }
        }
        else if (this.state.view === "ActionDetail") {
          if (barcodeData.barcodeType === "production_activities") {     
            await this.selectWorkOrder(barcodeData.record.work_order_id[0])     
            this.state.selectedComponent = this.state.components.find(x=>x.id == barcodeData.record.component_id[0])
            this.selectComponent(this.state.selectedComponent)
            const data = await this.orm.call(
              "mrp.workorder",
              "handle_package_scan",
              [
                this.state.selectedWorkOrder.id,      // workorder_id
                this.state.selectedComponent.id,      // component_id
                barcode,                              // qr_code rỗng
                this.state.employee.id,               // employee_id
                false,                                // button_type
                false,                                // force
                0,                                    // quantity (OK)
                0,                                    // ng_qty
                "" ,                                  // note
                false                                 // reason_id
              ],
              {}
            );
            this.updateSelectedWorkOrder(data)
          }
          this.state.view = "ActionDetail";
        }
      

    } 
    else {
        if (this.state.view === "ActionDetail" && barcode.includes('NG')) {
          const data = await this.orm.call(
            "mrp.workorder",
            "handle_package_scan",
            [
              this.state.selectedWorkOrder.id,      // workorder_id
              this.state.selectedComponent.id,      // component_id
              barcode,                              // qr_code rỗng
              this.state.employee.id,               // employee_id
              false,                                // button_type
              false,                                // force
              0,                                    // quantity (OK)
              1,                                    // ng_qty
              "" ,                                  // note
              false                                 // reason_id
            ],
            {}
          );
          this.updateSelectedWorkOrder(data)
        }
        else{
          this.notification.add(`Barcode: ${barcode} không hợp lệ!`, {
            type: "warning",
          });
          return;
        }
        
    }
  }


   
}

registry.category("actions").add("smartbiz_barcode.WorkOrder", WorkOrder);
