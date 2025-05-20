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
import { KeyPads } from "@smartbiz_barcode/Components/keypads";
import { DialogModal } from "./dialogModal";
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
      note:this.props.activity.note || '',
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
      note: this.state.note,
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
    "showOK",
    "showNG",
    "showPrint",
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
    });

    console.log({buttonStatus:this.props.buttonStatus});
  }
  
  getClass(line) {
    // console.log(line)
    let cl = " ";
    if (line.start && !line.finish) {
      if (!line.package_id){
        cl += "";
      } else
      cl += " bg-yellow";
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
  static props = ["document"];
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
      dialogFields:[]
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
  // =====================
  // hàm showModal universal
  // =====================
  showModal(title,action=''){
    const formMap = {
        ok_action:   [{name:'quantity',label:'Số lượng OK',type:'number', required: true}],
        ng_action:   [
            {name:'quantity',label:'Số lượng NG',type:'number', required: true},
            {name:'reason_id',label:'Lý do NG', type:'select', options: this.pauseReasons.filter(r => r.type === 'ng'), required: true },
            {name:'note',label:'Ghi chú',type:'textarea'},
        ],
        pause_action:[
            {name:'quantity',label:'Số lượng OK',type:'number', required: true},
            {name:'ng_qty',  label:'Số lượng NG',type:'number'},
            {name: 'reason_id', label:'Lý do tạm dừng', type: 'select', options: this.pauseReasons.filter(r => r.type === 'pause'), required: true },
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
    }
    this.state.showDialogModal = true;
  }

  // ---------------
  // closeModal giữ logic
  closeModal(title,data,action=''){
    if (['ok_action','ng_action','pause_action'].includes(action) && data){
        this._callHandlePackageScan(action,data);
    }else if (title==='Chọn trạm sản xuất' && data){
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
        vals.note || "" ,                      // note
        vals.reason_id || ""                       // reason_id
    ];
    console.log(args)
    const res = await this.orm.call(
        "mrp.workorder", "handle_package_scan", args, {}
    );
    this.updateSelectedWorkOrder(res);
}

  updateWorkOrders(){
    this.state.title = (this.state.workCenter.name || '-')
    this.state.workOrders = this.state.data.orders.filter(x=>x.workcenter_id == this.state.workCenter.id);
    //console.log({user:this.state.user,workCenter:this.state.workCenter})
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
    try {
      let domain  = [["state", "in", ["progress", "pending", "ready"]]]
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
      this.state.workOrders = data.orders.filter(x=>x.workcenter_id == this.state.workCenter.id);
        this.state.view = "WorkOrders"
      
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


  handleInput(event) {
    this.state.searchInput = event.target.value;
    this.search(); // Gọi hàm tìm kiếm
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
      if (this.state.workcenter) {
        this.state.workOrders = this.state.data.orders.filter(
          (x) => x.name === this.state.workcenter.name
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
      let domain  = [["state", "in", ["progress", "pending", "ready"]]]
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

    } else if (this.state.view === "ProductionActivity") {
      this.state.view = "ActionDetail";
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
      this.state.view = "ProductionActivity";
      console.log(this.state.selectedActivity);
    } else if (action == "delete") {
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
    } else if (action == "print") {
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
    
    if (this.state.selectedWorkOrder?.state != 'done'){
      this.state.buttonStatus.deleteActivity = false
    }
    console.log({selectedWorkOrder:this.state.selectedWorkOrder,deleteActivity:this.state.buttonStatus.deleteActivity})
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
    
    const pdfUrl = `/web/content?model=mrp.workorder&field=worksheet&id=${this.state.selectedWorkOrder.id}`;
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
    
    if (barcodeData && barcodeData.match) {
        if (this.state.view === "WorkOrders") {
          console.log("Barcode Data (ScanWorkCenter):", barcodeData);
          if (barcodeData.barcodeType === "employees") {
            this.state.employee = this.employees.find(x=>x.id == barcodeData.record.id);
          }
          if (barcodeData.barcodeType === "workcenters") {
            
            this.state.workCenter = this.workCenters.find(x=>x.id == barcodeData.record.id)

            let domain  = [["state", "in", ["progress", "pending", "ready"]]]
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
            console.log({selectedWorkOrder:this.state.selectedWorkOrder,selectedComponent:this.state.selectedComponent})
            const data = await this.orm.call(
              "mrp.workorder",
              "handle_package_scan",
              [
                ,
                this.state.selectedWorkOrder.id,
                this.state.selectedComponent.id,
                barcode,
                this.state.employee.id
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
                ,
                this.state.selectedWorkOrder.id,
                this.state.selectedComponent.id,
                barcode,
                this.state.employee.id
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
                ,
                this.state.selectedWorkOrder.id,
                this.state.selectedComponent.id,
                barcode,
                this.state.employee.id
              ],
              {}
            );
            this.updateSelectedWorkOrder(data)
          }
          this.state.view = "ActionDetail";
        }
      

      } else {
        if (this.state.view === "ActionDetail" && barcode.includes('NG')) {
          const data = await this.orm.call(
            "mrp.workorder",
            "handle_package_scan",
            [
              ,
              this.state.selectedWorkOrder.id,
              this.state.selectedComponent.id,
              barcode,
              this.state.employee.id
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
