/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { COMMANDS } from "@barcodes/barcode_handlers";
import { registry } from "@web/core/registry";
import { useService, useBus } from "@web/core/utils/hooks";
import * as BarcodeScanner from '@web/webclient/barcode/barcode_scanner';
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { View } from "@web/views/view";
import { ManualBarcodeScanner } from "@smartbiz_barcode/Components/manual_barcode";
import { url } from '@web/core/utils/urls';
import { utils as uiUtils } from "@web/core/ui/ui_service";
import { KeyPad } from "./keypad";
import { Selector } from "./selector";
import {DialogModal} from "@smartbiz/Components/dialogModal";
import { Packages,EditPackage,CreatePackages } from "@smartbiz_barcode/Components/Package";
import SmartBizBarcodePickingModel from "../Models/barcode_picking";
import { Component, EventBus, onPatched, onWillStart, useState, useSubEnv, xml } from "@odoo/owl";
import { CameraAI } from "@smartbiz_barcode/Components/camera_ai";

// Lets `barcodeGenericHandlers` knows those commands exist so it doesn't warn when scanned.
COMMANDS["O-CMD.MAIN-MENU"] = () => { };
COMMANDS["O-CMD.cancel"] = () => { };

const bus = new EventBus();



/**
 * Main Component
 * Gather the line information.
 * Manage the scan and save process.
 */

class StockPicking extends Component {
    static props = ["action?", "actionId?", "className?", "globalState?", "resId?"];
    static template = 'smartbiz_barcode.StockPicking';
    static components = {
        KeyPad, 
        Selector, 
        ManualBarcodeScanner,
        CameraAI,
        Packages,
        EditPackage,
        CreatePackages,
        DialogModal
    };
    setup() {
        this._t = _t;
        this.rpc = useService('rpc');
        this.orm = useService('orm');
        this.notification = useService('notification');
        this.dialog = useService('dialog');
        this.action = useService('action');
        this.home = useService("home_menu");
        //console.log(this.props)
        if(this.props.action.res_model === 'stock.picking.batch')
        {
            this.picking_id = false
            this.batch_id = this.props.action.context.active_id
        }
        if(this.props.action.res_model === 'stock.picking')
        {
            this.picking_id = this.props.action.context.active_id
            this.batch_id = false
        }
        console.log({picking_id:this.picking_id,batch_id:this.batch_id})
        const services = { rpc: this.rpc, orm: this.orm, notification: this.notification, action: this.action };
        const model = new SmartBizBarcodePickingModel('stock.picking', this.picking_id, services);
        useSubEnv({ model });
        this.lines = [];
        this.move = {};
        this._scrollBehavior = 'smooth';
        this.isMobile = uiUtils.isSmall();
        this.barcodeService = useService('barcode');
        useBus(this.barcodeService.bus, "barcode_scanned", (ev) => this.onBarcodeScanned(ev.detail.barcode));
        onWillStart(async () => {
            await this.initData()        
        });
        onPatched(() => {
            //console.log("Patched", this.state);
            this.env.model.data = this.state.data;
        });
        this.state = useState({
            view: "Move", // Could be also 'printMenu' or 'editFormView'.
            displayNote: false,
            inputValue: "",
            moves: [],
            lines: [],
            data: {},
            selectedPicking: 0,
            selectedMove: 0,
            selectedMoveLine: 0,
            detailTitle: '',
            picking: {},
            detailMoveLine: {},
            focus: 0,
            search: false,
            searchInput: "",
            showKeypad: false,
            showSelector: false,
            showNewProduct: false,
            showValidate: false,
            showSave: false,
            finished:false,
            finished_message:'',
            menuVisible:false,
            scannedLine:false,
            isSelector: true,
            activeTab:'OrderDetail',
            total_lines:0,
            scanned_lines:0,
            prompt: _t("Extract information to JSON"), 
            result: null,
            score: null,
            cameraActive: false,

            showDialogModal: false,
            modal: '',
        });

        this.records = [];
        this.multiSelect = false;
        this.selectorTitle = '';

        // ★ NEW: cấu hình đọc từ picking.type + cờ đã quét
        this.cfg = {
            scan_product: false,
            scan_source_location: false,
            scan_destination_location: false,
            scan_lot: false,
            scan_package: false,
            get_full_package: true,
            all_move_done: false,
            all_move_line_picked: false,
        };
        // Mỗi lần vào 1 move/line sẽ reset
        this.scanned = { product: false, source: false, dest: false, lot: false, package: false };

        // map sang biến cũ đang dùng trong code
        this.allowGetFullPackage = true;
        this.requiredAllMoveDone = false;
        this.requiredAllMoveLinePicked = false; // ★ NEW
        this.allowConfirmLackOrder = true;      // sẽ tự bật/tắt theo cấu hình

    }
    // ★ NEW: nạp cấu hình từ picking.type
    async loadPickingTypeConfig(data) {
        try {
            const fromArray = (v) => Array.isArray(v) ? v[0] : v;
            const ptId =
                data?.batch_picking_type_id ||
                fromArray(data?.picking_type_id) ||
                data?.picking_type_id?.id ||
                data?.picking_type_id;

            if (!ptId) return;

            const [pt] = await this.orm.read("stock.picking.type", [ptId], [
                "scan_product",
                "scan_source_location",
                "scan_destination_location",
                "scan_lot",
                "scan_package",
                "get_full_package",
                "all_move_done",
                "all_move_line_picked",
            ]);

            if (pt) {
                this.cfg = {
                    scan_product: !!pt.scan_product,
                    scan_source_location: !!pt.scan_source_location,
                    scan_destination_location: !!pt.scan_destination_location,
                    scan_lot: !!pt.scan_lot,
                    scan_package: !!pt.scan_package,
                    get_full_package: !!pt.get_full_package,
                    all_move_done: !!pt.all_move_done,
                    all_move_line_picked: !!pt.all_move_line_picked,
                };
                // Đồng bộ các biến logic sẵn có
                this.allowGetFullPackage = this.cfg.get_full_package;
                this.requiredAllMoveDone = this.cfg.all_move_done;
                this.requiredAllMoveLinePicked = this.cfg.all_move_line_picked;
                // Nếu bắt buộc đủ move thì không cho xác nhận thiếu
                this.allowConfirmLackOrder = !this.requiredAllMoveDone;
            }
        } catch (e) {
            console.warn("loadPickingTypeConfig failed", e);
        }
    }
    openCamera() {
        if (!this.state.prompt) {
            alert(_t("Please enter a prompt first!")); // ★ changed
            return;
        }
        this.state.menuVisible = false;
        this.state.cameraActive = true;
      }
      buildExpectedList() {
        // Lấy từ this.state.moves: bạn cần chắc các field sau có sẵn
        // ƯU TIÊN: default_code (mã) + product_name + (product_uom_qty - quantity)
        // Nếu không có default_code, tạm dùng product_name làm mã (ít ưu tiên)
        return (this.state.moves || []).map(m => {
          const ma = m.product_code || m.product_barcode || String(m.product_id);
          const ten = m.product_name_ || m.product_name || "";
          // lượng còn phải nhận = demand - picked (vì bạn đang chỉ dùng quantity)
          const so_yeu_cau = Math.max(0, Number(m.product_uom_qty || 0) - Number(m.quantity || 0));
          return { ma_part: ma, ten, so_yeu_cau };
        }).filter(x => x.so_yeu_cau > 0);
      }
    
    // === Helper 1: Tìm move theo mã AI (ma_part) → ưu tiên default_code → barcode → product_id (string)
_findMoveByMaPart(codeRaw) {
    const code = String(codeRaw || "").trim();
    return (this.state.moves || []).find((m) =>
      (m.product_code && String(m.product_code).trim() === code) ||
      (m.product_barcode && String(m.product_barcode).trim() === code) ||
      (String(m.product_id) === code)
    );
  }
  
  // === Helper 2: Tính số còn cần nhận (chỉ dùng quantity)
  _needOfMove(mv) {
    const need = (Number(mv.product_uom_qty || 0) - Number(mv.quantity || 0));
    return Math.max(0, this.roundToTwo(need));
  }
  
  // === Helper 3: Sinh serial fallback từ prefix
  _makeSerialNames(prefix, count) {
    const base = String(prefix || "").trim() || "SN";
    const now = new Date();
    const stamp = [
      now.getFullYear(),
      String(now.getMonth()+1).padStart(2,'0'),
      String(now.getDate()).padStart(2,'0'),
      String(now.getHours()).padStart(2,'0'),
      String(now.getMinutes()).padStart(2,'0'),
      String(now.getSeconds()).padStart(2,'0'),
    ].join('');
    return Array.from({ length: count }, (_, i) => `${base}-${stamp}-${i+1}`);
  }
  
  // === Hàm xử lý kết quả từ Camera AI ===
  // onResult(answer, score, cancelled)
  async closeCamera(answer, score, cancelled = false) {
    try {
      // Hủy → tắt modal
      if (cancelled) {
        this.state.cameraActive = false;
        return;
      }
  
      // Validate payload
      const receivedMap = answer && answer.received_map;
      const serialsMap  = (answer && answer.serials_map) || {};
      if (!receivedMap || typeof receivedMap !== "object") {
        this.notification.add(this._t("Không có dữ liệu hợp lệ từ Camera AI."), { type: "warning" });
        this.state.cameraActive = false;
        return;
      }
  
      // Lưu kết quả AI (nếu cần hiển thị)
      this.state.result = answer;
      this.state.score  = score;
  
      // Prefix lô lấy từ picking (theo yêu cầu)
      const lotPrefix =
        this.state.data?.lot_name ||
        (this.state.data?.order && this.state.data.order[0]?.lot_name) ||
        "";
  
      const applied = [];
      const skippedNoLotPrefix = [];
      const skippedUnknownMove = [];
  
      // Xử lý từng mã
      for (const [ma_part, gotRaw] of Object.entries(receivedMap)) {
        let got = Number(gotRaw) || 0;
        if (got <= 0) continue;
  
        const move = this._findMoveByMaPart(ma_part);
        if (!move) {
          skippedUnknownMove.push({ ma_part, qty: got });
          continue;
        }
  
        const need = this._needOfMove(move);
        if (!need) continue;
  
        const tracking = move.product_tracking || "none";
  
        // Hàng không tracking: 1 line quantity = min(need, got)
        if (tracking === "none") {
          const qtyToAdd = Math.min(need, got);
          if (qtyToAdd <= 0) continue;
  
          const values = {
            id: false,
            product_id: move.product_id,
            product_uom_id: move.product_uom_id,
            quantity: this.roundToTwo(qtyToAdd),
            location_id: move.location_id,
            location_dest_id: move.location_dest_id,
            lot_id: false,
            lot_name: "",
            package_id: false,
            result_package_id: false,
            picked: true,
            picking_id: this.picking_id,
          };
          const res = await this.orm.call("stock.picking", "save_data", [, this.picking_id, values, this.batch_id], {});
          this.state.data  = res;
          this.state.moves = this.state.data.moves.sort((a, b) => b.product_name.localeCompare(a.product_name));
          applied.push({ ma_part, qty: qtyToAdd });
          continue;
        }
  
        // Các loại cần lô/serial phải có prefix từ picking
        if (!lotPrefix) {
          skippedNoLotPrefix.push({ ma_part, qty: got, reason: "missing picking.lot" });
          continue;
        }
  
        // Hàng LOT: 1 line với lot_name = lotPrefix
        if (tracking === "lot") {
          const qtyToAdd = Math.min(need, got);
          if (qtyToAdd <= 0) continue;
  
          const values = {
            id: false,
            product_id: move.product_id,
            product_uom_id: move.product_uom_id,
            quantity: this.roundToTwo(qtyToAdd),
            location_id: move.location_id,
            location_dest_id: move.location_dest_id,
            lot_id: false,
            lot_name: lotPrefix,  // lấy từ picking
            package_id: false,
            result_package_id: false,
            picked: true,
            picking_id: this.picking_id,
          };
          const res = await this.orm.call("stock.picking", "save_data", [, this.picking_id, values, this.batch_id], {});
          this.state.data  = res;
          this.state.moves = this.state.data.moves.sort((a, b) => b.product_name.localeCompare(a.product_name));
          applied.push({ ma_part, qty: qtyToAdd });
          continue;
        }
  
        // Hàng SERIAL: nhiều line, mỗi line quantity = 1
        if (tracking === "serial") {
          // Ưu tiên dùng serial do AI trả (serials_map)
          let serials = Array.isArray(serialsMap[ma_part])
            ? serialsMap[ma_part].map(s => String(s).trim()).filter(Boolean)
            : [];
          // Nếu AI không trả serial → dùng fallback tạo từ prefix
          const maxCount = Math.min(need, Math.floor(got));
          if (!serials.length) serials = this._makeSerialNames(lotPrefix, maxCount);
          // Cắt theo nhu cầu
          serials = serials.slice(0, maxCount);
  
          for (const sn of serials) {
            const values = {
              id: false,
              product_id: move.product_id,
              product_uom_id: move.product_uom_id,
              quantity: 1,                 // mỗi serial = 1
              location_id: move.location_id,
              location_dest_id: move.location_dest_id,
              lot_id: false,
              lot_name: sn,                // backend sẽ tự tạo lot nếu chưa có
              package_id: false,
              result_package_id: false,
              picked: true,
              picking_id: this.picking_id,
            };
            const res = await this.orm.call("stock.picking", "save_data", [, this.picking_id, values, this.batch_id], {});
            this.state.data  = res;
            this.state.moves = this.state.data.moves.sort((a, b) => b.product_name.localeCompare(a.product_name));
          }
          applied.push({ ma_part, qty: serials.length });
          continue;
        }
      }
  
      // Cập nhật UI
      this.updateButton();
  
      // Thông báo
      if (applied.length) {
        const total = applied.reduce((a, r) => a + Number(r.qty || 0), 0);
        this.notification.add(
          this._t("Đã ghi nhận từ Camera AI cho %s mã, tổng số lượng %s.")
            .replace("%s", applied.length).replace("%s", total),
          { type: "success" }
        );
      }
      if (skippedNoLotPrefix.length) {
        this.notification.add(
          this._t("Bỏ qua %s mã vì chưa có số lô trên phiếu (picking.lot).")
            .replace("%s", skippedNoLotPrefix.length),
          { type: "warning" }
        );
      }
      if (skippedUnknownMove.length) {
        this.notification.add(
          this._t("%s mã không khớp với danh sách sản phẩm của phiếu.")
            .replace("%s", skippedUnknownMove.length),
          { type: "warning" }
        );
        console.warn("AI unknown items:", skippedUnknownMove);
      }
    } catch (e) {
      this.notification.add(this._t("Lỗi xử lý kết quả Camera AI: %s").replace("%s", e?.message || e), { type: "danger" });
    } finally {
      this.state.cameraActive = false;
    }
  }
  
    roundToTwo(num) {
        return Math.round(num * 100) / 100;
    }
    toggleMenu = () => {
        this.state.menuVisible = !this.state.menuVisible;
    }
    async initData() {
        const data = await this.orm.call('stock.picking', 'get_data', [, this.picking_id, this.batch_id], {});
        this.state.moves = data.moves.sort((a, b) => b.product_name.localeCompare(a.product_name));
        this.state.data = data;
        await this.loadPickingTypeConfig(data); // ★ NEW
        this.updateButton();
        if (this.batch_id && data.moves.length === 0) {
            await this.createBatch(this.state.data.batch_picking_type_id);
        }
        this.env.model.data = this.state.data;
    }
    
    async createBatch(picking_type_id){
        if(picking_type_id)
        {
            this.clearSelector()
            this.records = await this.orm.searchRead("stock.picking", [['picking_type_id','=',picking_type_id],['batch_id','=',false],['state','not in',['done','draft','cancel']]], ["name","origin"]) 
            this.multiSelect = true
            this.selectorTitle = "Select Transfer";   
            this.selectorFunction = _t("Select Transfer");
            this.state.showSelector = true
            
        }
        else
        {
            this.records = await this.orm.searchRead("stock.picking.type", [], ["display_name"]) 
            this.multiSelect = false
            this.selectorTitle = "Select Picking Type";
            this.selectorFunction = _t("Select Picking Type"); 
            this.state.showSelector = true
        }

    }
    filterArrayByString(array, queryString) {
        const queryStringLower = queryString.toLowerCase(); // Chuyển đổi queryString sang chữ thường để tìm kiếm không phân biệt chữ hoa chữ thường

        return array.filter(obj => {
            // Duyệt qua mỗi key của object để kiểm tra
            return Object.keys(obj).some(key => {
                const value = obj[key];
                // Chỉ xét các giá trị là chuỗi hoặc số
                if (typeof value === 'string' || typeof value === 'number') {
                    return value.toString().toLowerCase().includes(queryStringLower);
                }
                return false;
            });
        });
    }
    searchClick() {
        this.state.search = this.state.search ? false : true;
        this.state.searchInput = '';
        if (!this.state.search) {
            this.state.moves = this.state.data.moves.sort((a, b) => b.product_name.localeCompare(a.product_name));
            this.state.lines = this.lines
        }
    }

    handleInput(event) {
        this.state.searchInput = event.target.value;
        this.search();
    }
    search() {
        if (this.state.searchInput !== '') {
            if (this.state.view === 'Move') {
                this.state.moves = this.filterArrayByString(this.state.data.moves, this.state.searchInput).sort((a, b) => b.product_name.localeCompare(a.product_name));
            }
            if (this.state.view === 'Move_line') {
                this.state.lines = this.filterArrayByString(this.lines, this.state.searchInput)
            }
        }
        else {
            this.state.moves = this.state.data.moves.sort((a, b) => b.product_name.localeCompare(a.product_name));
            this.state.lines = this.lines
        }
    }
    changeTab(tab) { 
        this.state.activeTab = tab;
        this.updateButton();
    }
    focusClass(item) {
        if (item === this.state.focus) {
            return "s_focus"
        }
        return ""
    }

    focusClick(item) {
        if (item == this.state.focus)
            this.state.focus = 0
        else
            this.state.focus = item
    }
    focusCompute()
    {
        if(!this.state.detailMoveLine.lot_id && !this.state.detailMoveLine.lot_name)
        {
            this.state.focus = 0
        }
        else
        {
            this.state.focus = 0
        }
    }

    async save() {
        // ★ NEW: enforce bắt buộc quét theo cấu hình
        const mustScan = [];
        if (this.cfg.scan_source_location && !this.scanned.source) mustScan.push(this._t("vị trí nguồn"));
        if (this.cfg.scan_destination_location && !this.scanned.dest) mustScan.push(this._t("vị trí đích"));
        if (this.cfg.scan_lot && this.state.detailMoveLine.product_tracking !== "none" && !this.scanned.lot) {
            mustScan.push(this._t("lot/serial"));
        }
        if (this.cfg.scan_package) {
            const hasPkg = !!(this.state.detailMoveLine.package_id || this.state.detailMoveLine.result_package_id);
            if (!hasPkg && !this.scanned.package) {
                mustScan.push(this._t("gói (package)"));
            }
        }
        if (mustScan.length) {
            this.notification.add(
                this._t("Bạn phải QUÉT: %s trước khi lưu.").replace("%s", mustScan.join(", ")),
                { type: "warning" }
            );
            return;
        }

        this.state.data = await this.orm.call('stock.picking', 'save_data', [,this.picking_id, this.state.detailMoveLine,this.batch_id], {});
        this.state.moves = this.state.data.moves.sort((a, b) => b.product_name.localeCompare(a.product_name));
        this.lines = this.state.data.move_lines.filter(x => x.move_id === this.state.detailMoveLine.move_id)
        this.state.lines = this.lines
        var lot_id = this.state.detailMoveLine.lot_id
        var lot_name = this.state.detailMoveLine.lot_name
        this.editMove(this.state.detailMoveLine.move_id)
        this.state.detailMoveLine.lot_id = lot_id
        this.state.detailMoveLine.lot_name = lot_name
        this.focusCompute()

    }
    async doneMove(id) {
        this.state.data = await this.orm.call('stock.picking', 'done_move', [,this.picking_id, id,this.batch_id], {});
        this.state.moves = this.state.data.moves.sort((a, b) => b.product_name.localeCompare(a.product_name));
    }
    async doneMoveLine(id) {
        this.state.data = await this.orm.call('stock.picking', 'done_move_line', [,this.picking_id, id,this.batch_id], {});
        this.state.moves = this.state.data.moves.sort((a, b) => b.product_name.localeCompare(a.product_name));
    }
    async actionDone(id) {
        const params = {
            title: _t("Confirm Transfer"),                       // ★ changed
            body: _t("Are you sure you want to validate this picking?"), // ★ changed
            confirmLabel: _t("Yes, Confirm"),                    // ★ changed
            cancelLabel: _t("Cancel"),                           // ★ changed
            confirm: async () => {
                var res = await this.orm.call('stock.picking', 'barcode_action_done', [,this.picking_id,this.batch_id], {context:{skip_backorder: true,display_detailed_backorder: true}});
                if(res.action)
                {
                    res = await this.action.doAction(res.action)
                    console.log(res)
                }
                else
                {
                    this.state.data = res
                    this.state.moves = this.state.data.moves.sort((a, b) => b.product_name.localeCompare(a.product_name));
                    this.updateButton()
                }
            },
            cancel: () => { },

        };
        this.dialog.add(ConfirmationDialog, params);  
        
    }
    async cancelOrder() {
        this.state.menuVisible = false;
        const params = {
            title: _t("Cancel Transfer"),
            body: _t("Are you sure you want to cancel this picking?"),
            confirmLabel: _t("Yes, Cancel"),
            cancelLabel: _t("Back"),
            confirm: async () => {
                var res = await this.orm.call('stock.picking', 'cancel_order', [,this.picking_id,this.batch_id],{});
                this.state.data = res
                this.state.moves = this.state.data.moves.sort((a, b) => b.product_name.localeCompare(a.product_name));
                this.updateButton()
                
            },
            cancel: () => { },
        };
        this.dialog.add(ConfirmationDialog, params);  
        
    }
    async unReserve() {
        this.state.menuVisible = false;
        if(this.state.view == "Move") {
            const params = {
                title: _t("Unreserve Confirmation"),
                body: _t("Are you sure you want to unreserve this picking?"),
                confirmLabel: _t("Yes, Unreserve"),
                cancelLabel: _t("Cancel"),
                confirm: async () => {
                    var res = await this.orm.call('stock.picking', 'unreserve', [,this.picking_id,this.batch_id],{});
                    console.log(res)
                    this.state.data = res
                    this.state.moves = this.state.data.moves.sort((a, b) => b.product_name.localeCompare(a.product_name));
                    this.updateButton()
                },
                cancel: () => { },
          
            };
            this.dialog.add(ConfirmationDialog, params);
        } 
        if(this.state.view == "Move_line") {
            const unpickedLineIds = this.lines.filter(x => !x.picked).map(line => line.id);
            const params = {
                title: _t("Delete Confirmation"),
                body: _t("Are you sure you want to delete all unpicked move lines? This action cannot be undone."),
                confirmLabel: _t("Yes, Delete"),
                cancelLabel: _t("Cancel"),
                confirm: async () => {
                    this.state.data = await this.orm.call('stock.picking', 'delete_move_line', [,this.picking_id, unpickedLineIds,this.batch_id], {});
                    this.state.moves = this.state.data.moves.sort((a, b) => b.product_name.localeCompare(a.product_name));

                    this.lines = this.state.data.move_lines.filter(x => x.move_id === this.state.detailMoveLine.move_id);
                    this.state.lines = this.lines;
                    var lot_id = this.state.detailMoveLine.lot_id;
                    var lot_name = this.state.detailMoveLine.lot_name;
                    this.editMove(this.state.detailMoveLine.move_id);
                    this.state.detailMoveLine.lot_id = lot_id;
                    this.state.detailMoveLine.lot_name = lot_name;
                    this.updateButton()
                },
                cancel: () => { },

            };
            this.dialog.add(ConfirmationDialog, params);
        } 
    }
    
    async createPack(package_name=false) {
        var data = await this.orm.call('stock.picking', 'create_pack', [,this.picking_id, this.state.detailMoveLine, package_name,this.batch_id], {});       
        var line =  data.move_lines.find(aItem => !(this.state.data.move_lines.some(bItem => bItem.id === aItem.id)) )
        this.state.data = data
        this.state.moves = this.state.data.moves.sort((a, b) => b.product_name.localeCompare(a.product_name));
        this.lines = this.state.data.move_lines.filter(x => x.move_id === this.state.detailMoveLine.move_id)
        this.state.lines = this.lines
        var lot_id = this.state.detailMoveLine.lot_id
        var lot_name = this.state.detailMoveLine.lot_name
        if(line)
        {
            //this.linePrint(line.id)
            this.selectedMoveLine = line.id
        }
        else
        {
           //this.linePrint(this.state.detailMoveLine.id)
        }
        this.editMove(this.state.detailMoveLine.move_id)
        this.state.detailMoveLine.lot_id = lot_id
        this.state.detailMoveLine.lot_name = lot_name
    }
    async deleteMoveLine(id) {
        const params = {
            title: _t("Delete Confirmation"),
            body: _t("Are you sure you want to delete this move-line? This action cannot be undone."),
            confirmLabel: _t("Yes, Delete"),
            cancelLabel: _t("Cancel"),
            confirm: async () => {
                this.state.data = await this.orm.call('stock.picking', 'delete_move_line', [,this.picking_id, id,this.batch_id], {});
                this.state.moves = this.state.data.moves.sort((a, b) => b.product_name.localeCompare(a.product_name));

                this.lines = this.state.data.move_lines.filter(x => x.move_id === this.state.detailMoveLine.move_id);
                this.state.lines = this.lines;
                var lot_id = this.state.detailMoveLine.lot_id;
                var lot_name = this.state.detailMoveLine.lot_name;
                this.editMove(this.state.detailMoveLine.move_id);
                this.state.detailMoveLine.lot_id = lot_id;
                this.state.detailMoveLine.lot_name = lot_name;
                this.updateButton()
            },
            cancel: () => { },
        };
        this.dialog.add(ConfirmationDialog, params);
    }
    async deleteMove(id) {
        const params = {
            title: _t("Delete Confirmation"),
            body: _t("Are you sure you want to delete this move? This action cannot be undone."),
            confirmLabel: _t("Yes, Delete"),
            cancelLabel: _t("Cancel"),
            confirm: async () => {
                this.state.data = await this.orm.call('stock.picking', 'delete_move', [,this.picking_id, id,this.batch_id], {});
                this.state.moves = this.state.data.moves.sort((a, b) => b.product_name.localeCompare(a.product_name));
                this.updateButton()
      
            },
            cancel: () => { },

        };
        this.dialog.add(ConfirmationDialog, params);
    }
    cancel() {
        this.editMove(this.state.detailMoveLine.move_id);
    }
    clearPackage() {
        this.state.detailMoveLine.package_id = false
        this.state.detailMoveLine.package_name = ''
    }
    clearResultPackage() {
        this.state.detailMoveLine.result_package_id = false
        this.state.detailMoveLine.result_package_name = ''
    }
    editMove(id) {
        this.state.view = "Move_line";
        this.move = this.state.data.moves.find(x => x.id === id)
        var move = this.move;
        this.state.detailTitle = this.move.picking_name
        this.picking_id = this.move.picking_id
        this.state.search = false;
        this.state.searchInput = '';
        this.lines = this.state.data.move_lines.filter(x => x.move_id === id)
        this.state.lines = this.lines
        var location_id = this.state?.detailMoveLine?.location_id ? this.state.detailMoveLine.location_id : move.location_id
        var location_name = this.state?.detailMoveLine?.location_id ? this.state.detailMoveLine.location_name : move.location_name
        var lot_id = this.state?.detailMoveLine?.lot_id ? this.state.detailMoveLine.lot_id : false
        var lot_name = this.state?.detailMoveLine?.lot_id ? this.state.detailMoveLine.lot_name : this.state.data.lot_name
        this.state.detailMoveLine = {
            id: 0,
            move_id: move.id,
            product_id: move.product_id,
            product_name: move.product_name,
            location_name: location_name,
            location_id: location_id,
            location_dest_name: move.location_dest_name,
            location_dest_id: move.location_dest_id,
            lot_id: lot_id,
            lot_name: lot_name,
            product_uom_id: move.product_uom_id,
            package_id: move.package_id,
            package_name: move.package_name,
            result_package_id: move.result_package_id,
            result_package_name: move.result_package_name,
            product_uom_qty: move.product_uom_qty,
            quantity: 0,
            quantity_done: move.quantity,
            quantity_need: this.roundToTwo(move.product_uom_qty - move.quantity),
            product_uom: move.product_uom,
            product_tracking: move.product_tracking,
            picking_type_code: move.picking_type_code,
            state: 'draft',
            package: true,
            picking_id:this.picking_id,
        }
        // ★ NEW: reset cờ đã quét theo yêu cầu cấu hình
        this.scanned = {
            product: !this.cfg.scan_product,                       // nếu không bắt buộc quét → coi như OK
            source: !this.cfg.scan_source_location,
            dest: !this.cfg.scan_destination_location,
            lot: !this.cfg.scan_lot,
            package: !this.cfg.scan_package,
        };
        this.updateButton()
        this.focusCompute()
    }
    async linePrint(id){
        let print = await this.orm.call('stock.picking', 'print_line', [,id], {});
        console.log({print})
    }
    editLine(id) {
        var line = this.lines.find(x => x.id === id);
        var move = this.move;
        this.state.detailMoveLine = {
            id: id,
            move_id: line.move_id,
            product_id: line.product_id,
            product_name: line.product_name,
            location_name: line.location_name,
            location_id: line.location_id,
            product_uom_id: line.product_uom_id,
            location_dest_name: line.location_dest_name,
            location_dest_id: line.location_dest_id,
            lot_id: line.lot_id,
            lot_name: line.lot_name,
            package_id: line.package_id,
            package_name: line.package_name,
            result_package_id: line.result_package_id,
            result_package_name: line.result_package_name,
            product_uom_qty: move.product_uom_qty,
            quantity: line.quantity,
            quantity_done: move.quantity,
            quantity_need: this.roundToTwo(move.product_uom_qty - move.quantity + line.quantity),
            product_uom: move.product_uom,
            product_tracking: move.product_tracking,
            picking_type_code: move.picking_type_code,
            state: line.state,
            package: true,
            picking_id:this.picking_id,

        }
        this.updateButton()
        this.focusCompute()
    }


    updateQuantity() {
        this.state.detailMoveLine.quantity = this.state.detailMoveLine.quantity_need
        this.updateButton()
    }
    editQuantity() {
        this.state.showKeypad = true
    }

    async openSelector(option) {
        if (option == 1) {
            //Open create packages
            this.state.isSelector = false;
            this.state.menuVisible = false;
            this.selectorTitle = "Split Packages";
            this.selectorFunction = _t("Split Packages");
        }
        if (option == 8) {
            //Đóng nhiều packge một lúc
            this.state.isSelector = false;
            this.state.menuVisible = false;
            this.selectorTitle = "Bulk Pack";
            this.selectorFunction = _t("Bulk Pack");
        }
        if (option == 9) {
            //Nhận theo số sê-ri
            this.state.isSelector = false;
            this.state.menuVisible = false;
            this.records = this.state.lines;
            this.selectorTitle = "Receive by Serial"; 
            this.selectorFunction = _t("Receive by Serial");
        }
        if (option == 2)//Chọn số Lot
        {
            
            this.records = await this.orm.searchRead('stock.lot',[['product_id','=',this.move.product_id]], ['id', 'name']) 
            
            this.multiSelect = false
            this.selectorTitle = "Select Lot/Serial";
            this.selectorFunction = _t("Select Lot/Serial");
        }
        if (option == 3)//Chọn vị trí nguồn
        {
            this.records = this.state.data.locations
            this.multiSelect = false
            this.selectorTitle = "Select Source Location";
            this.selectorFunction = _t("Select Source Location");
        }
        if (option == 4)//Chọn vị trí đích
        {
            this.records = this.state.data.locations
            this.multiSelect = false
            this.selectorTitle = "Select Destination Location"; 
            this.selectorFunction = _t("Select Destination Location");
        }
        if (option == 5)//Chọn gói nguồn
        {
            this.records = this.state.data.packages
            this.multiSelect = false
            this.selectorTitle = "Select Source Package"; 
            this.selectorFunction = _t("Select Source Package");
        }
        if (option == 6)//Chọn gói đích
        {
            this.records = this.state.data.packages
            this.multiSelect = false
            this.selectorTitle = "Select Destination Package";
            this.selectorFunction = _t("Select Destination Package");
        }
        this.state.showSelector = true

    }
    async newProduct(){
        if (this.cfg.scan_product) {
            this.notification.add(this._t("Cấu hình yêu cầu QUÉT sản phẩm, không được chọn tay."), { type: "warning" });
            return;
        }
        this.records = await this.orm.searchRead("product.product", [], ["display_name"]) 
        this.multiSelect = false
        this.selectorTitle = "Select Product"; 
        this.selectorFunction = _t("Select Product");
        this.state.showSelector = true
    }
    clearSelector() {
        this.records = []
        this.multiSelect = false
        this.selectorTitle = ""
        this.selectorFunction = "";
        this.state.showSelector = false;
        this.state.isSelector = true;
        this.updateButton()
    }
    async closeSelector(data) {
        if (!data) {
            this.clearSelector();
            return;
        }
    
        // ----- 1) SPLIT PACKAGES -----
        if (this.selectorTitle === "Split Packages") {
            this.clearSelector();
            this.state.data = await this.orm.call(
                "stock.picking",
                "save_lines_bulk",
                [, this.picking_id, data, this.batch_id],
                {}
            );
            
            // Sau đó sort, filter một lần
            this.state.moves = this.state.data.moves.sort((a, b) => b.product_name.localeCompare(a.product_name));
            this.lines = this.state.data.move_lines.filter((x) => x.move_id === (data[0]?.move_id ?? this.state.detailMoveLine.move_id));
            this.state.lines = this.lines;
            
        }
    
        // ----- 2) BULK PACK -----
        if (this.selectorTitle === "Bulk Pack") {
            this.clearSelector();
            this.state.data = await this.orm.call(
                "stock.picking",
                "save_lines_bulk",
                [, this.picking_id, data, this.batch_id],
                {}
            );
            
            // Sau đó sort, filter một lần
            this.state.moves = this.state.data.moves.sort((a, b) => b.product_name.localeCompare(a.product_name));
            this.lines = this.state.data.move_lines.filter((x) => x.move_id === (data[0]?.move_id ?? this.state.detailMoveLine.move_id));
            this.state.lines = this.lines;
            
        }
    
        // ----- 3) RECEIVE BY SERIAL -----
        if (this.selectorTitle === "Receive by Serial") {
            this.clearSelector();
            this.state.data = await this.orm.call(
                "stock.picking",
                "save_lines_bulk",
                [, this.picking_id, data, this.batch_id],
                {}
            );
            
            // Sau đó sort, filter một lần
            this.state.moves = this.state.data.moves.sort((a, b) => b.product_name.localeCompare(a.product_name));
            this.lines = this.state.data.move_lines.filter((x) => x.move_id === (data[0]?.move_id ?? this.state.detailMoveLine.move_id));
            this.state.lines = this.lines;
            
        }
    
        // ----- 4) SELECT LOT / SERIAL -----
        if (this.selectorTitle === "Select Lot/Serial") {
            this.clearSelector();
            if (data.id) {
                this.state.detailMoveLine.lot_id = data.id;
                this.state.detailMoveLine.lot_name = data.name;
            } else {
                this.state.detailMoveLine.lot_id = false;
                this.state.detailMoveLine.lot_name = data; // free text
            }
            
        }
    
        // ----- 5) SELECT SOURCE / DEST LOCATIONS -----
        if (this.selectorTitle === "Select Source Location") {
            this.state.detailMoveLine.location_id = data.id;
            this.state.detailMoveLine.location_name = data.display_name;
            this.clearSelector();
        }
        if (this.selectorTitle === "Select Destination Location") {
            this.state.detailMoveLine.location_dest_id = data.id;
            this.state.detailMoveLine.location_dest_name = data.display_name;
            this.clearSelector();
        }
    
        // ----- 6) SELECT SOURCE / DEST PACKAGES -----
        if (this.selectorTitle === "Select Source Package") {
            this.state.detailMoveLine.package_id = data.id;
            this.state.detailMoveLine.package_name = data.name;
            this.clearSelector();
        }
        if (this.selectorTitle === "Select Destination Package") {
            if (data.id) {
                this.state.detailMoveLine.result_package_id = data.id;
                this.state.detailMoveLine.result_package_name = data.name;
                this.clearSelector();
            } else {
                await this.createPack(data);   // free-text package name
                this.clearSelector();
            }
        }
    
        // ----- 7) SELECT PRODUCT -----
        if (this.selectorTitle === "Select Product") {
            const product_id = data.product_id;
            const name = data.display_name;
            const product_uom_qty = data.quantity || 0;
            const location_id = this.state.data.location_id;
            const location_dest_id = this.state.data.location_dest_id;
    
            const values = {
                picking_id: this.picking_id,
                product_id,
                name,
                location_id,
                location_dest_id,
                product_uom_qty,
            };
    
            const res = await this.orm.call(
                "stock.picking",
                "create_move",
                [, this.picking_id, values, this.batch_id],
                {}
            );
            this.state.data = res.data;
            this.state.moves = this.state.data.moves.sort(
                (a, b) => b.product_name.localeCompare(a.product_name)
            );
            this.state.selectedMove = res.move_id;
            this.clearSelector();
        }
    
        // ----- 8) SELECT TRANSFER (add to batch) -----
        if (this.selectorTitle === "Select Transfer") {
            const values = { picking_ids: data, state: "in_progress" };
            this.state.data = await this.orm.call(
                "stock.picking",
                "update_batch_picking",
                [, this.picking_id, values, this.batch_id],
                {}
            );
            this.state.moves = this.state.data.moves.sort(
                (a, b) => b.product_name.localeCompare(a.product_name)
            );
            this.clearSelector();
        }
    
        // ----- 9) SELECT PICKING TYPE (create new batch) -----
        if (this.selectorTitle === "Select Picking Type") {
            await this.createBatch(data.id);
        }
    }
    
    moveClass(line) {
        var cl = "s_move-line";
        if (line.id === this.state.selectedMove) {
            cl += " s_selectedItem"
            this.scrollToSelectedMove();
        }
        if(line.all_lines_picked)
        {
            if (line.quantity == line.product_uom_qty) {
                cl += " s_move_done"
            }
            else if(line.quantity > line.product_uom_qty) {
                cl += " s_move_over_demand"
            }
            else{
                cl += " s_move_under_demand"
            }
        }
        else if(line.picked)
        {
            cl += " s_move_under_demand"
        }
        
        return cl;
    }
    lineClass(line) {
        var cl = "s_move-line";
        if (line.id === this.state.selectedMove) {
            cl += " s_selectedItem"
        }
        if (line.picked) {
            cl += " s_move_line_done"
            this.scrollToSelectedMove();
        }
        else{
            if(line.id == this.state.scannedLine.id){
                cl += " s_move_line_scanned_package"
            }

        }
        return cl;
    }
    footerClass() {
        var cl = "s_footer";
        if (this.state.view === "Move") {
            if (this.state.data.state === "done"){
                cl += " s_footer_done";
            }
        }
        return cl;
    }
    async showDialogModal(title, action = '', defaultValues = null) {
        // Nạp options tối thiểu nếu chưa có
        // (Bạn có thể bỏ qua phần nạp nếu đã tự có sẵn this.state.partners/locations/users)
        if (!this.state.partners) {
          const partners = await this.orm.searchRead("res.partner", [], ["name","display_name"], { limit: 200 });
          this.state.partners = partners.map(p => ({ id: p.id, name: p.name }));
        }
        if (!this.state.locations) {
          const locs = await this.orm.searchRead("stock.location", [], ["complete_name"], { limit: 200 });
          this.state.locations = locs.map(l => ({ id: l.id, name: l.complete_name }));
        }
        if (!this.state.users) {
          const users = await this.orm.searchRead("res.users", [], ["name"], { limit: 200 });
          this.state.users = users.map(u => ({ id: u.id, name: u.name }));
        }
      
        // Lấy picking hiện tại làm mặc định nếu caller không truyền defaultValues
        const p =  this.state.data || {};
        const safe = (v) => (Array.isArray(v) ? v[0] : v) || "";
        // scheduled_date nên là UTC "YYYY-MM-DD HH:mm:ss" (Dialog đã tự quy đổi local/UTC)
        const scheduled = p.scheduled_date
          ? String(p.scheduled_date).replace("T", " ").slice(0, 19)
          : "";
      
        const formMap = {
          edit_picking_overview: [
            { name: "name",              label: "Tên phiếu",     type: "text",           readonly: true },
            { name: "partner_id",        label: "Liên hệ",        type: "select", options: this.state.partners || [], required: false, dialog: true },
            { name: "location_id",       label: "Vị trí nguồn",   type: "select", options: this.state.locations || [], required: true,  dialog: true },
            { name: "location_dest_id",  label: "Vị trí đích",    type: "select", options: this.state.locations || [], required: true,  dialog: true },
            { name: "user_id",           label: "Người phụ trách",type: "select", options: this.state.users || [],    required: false, dialog: true },
            { name: "origin",            label: "Chứng từ gốc",   type: "text" },
            { name: "scheduled_date",    label: "Ngày kế hoạch",  type: "datetime-local" },
          ],
        };
      
        // Gán state mở dialog
        this.state.dialogTitle  = title;
        this.state.dialogAction = action;
      
        if (title === "Chọn trạm sản xuất") {
          this.state.dialogRecords = this.workCenters;
          this.state.dialogFields  = [];
        } else {
          this.state.dialogFields  = formMap[action] || [];
          this.state.dialogRecords = []; // form mode
      
          // Ghép default cho form
          this.state.dialogDefault = {
            id: p.id || null,
            name: p.name || "",
            partner_id: safe(p.partner_id),
            location_id: safe(p.location_id),
            location_dest_id: safe(p.location_dest_id),
            user_id: safe(p.user_id),
            origin: p.origin || "",
            scheduled_date: scheduled || "",
          };
        }
        this.state.showDialogModal = true;
      }
      
    
      async closeDialogModal(title, data, action = "") {
        try {
          if (action === "edit_picking_overview" && data) {
            // Chuẩn hóa giá trị ghi
            const pickingId = this.picking_id;
            if (!pickingId) throw new Error("Thiếu ID stock.picking để cập nhật.");
      
            const vals = {
              // các many2one ghi bằng id hoặc false
              partner_id:        data.partner_id        || false,
              location_id:       data.location_id       || false,
              location_dest_id:  data.location_dest_id  || false,
              user_id:           data.user_id           || false,
              // text / datetime
              origin:            data.origin            || "",
              scheduled_date:    data.scheduled_date    || null, // UTC "YYYY-MM-DD HH:mm:ss"
              // name chỉ xem readonly (không ghi)
            };
      
            await this.orm.write("stock.picking", [pickingId], vals);
      
            this.initData(); // reload toàn bộ dữ liệu
          }
        } catch (e) {
          console.error("Cập nhật stock.picking lỗi:", e);
          if (this.notification) {
            this.notification.add(`Lỗi: ${e.message || e}`, { type: "danger" });
          }
        } finally {
          // reset dialog
          this.state.showDialogModal = false;
          this.state.dialogTitle     = "";
          this.state.dialogAction    = "";
          this.state.dialogFields    = [];
          this.state.dialogRecords   = [];
        }
      }
      
    async showModal(modal,data){   
        
        if(data && modal =="editPackage"){
            let cl = this.state.data.finish_packages.find(x=>x.id ==data.id).lines;
            let line = await this.orm.call(
                "stock.picking","unpacked_move_lines", [, this.picking_id], {}
            ) 
            line = [...cl,...line]
            let unpacked_move_lines = []

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
            "stock.picking",
            "update_package",
            [, this.picking_id,this.batch_id,data],
            {}
            );

            this.updateData(values)
        }
        if(data && modal =="createPackages")
            {
            let values =  await this.orm.call(
                "stock.picking",
                "create_packages",
                [, this.picking_id,this.batch_id,data],
                {}
            );
            this.updateData(values)
            }
        this.state.modal = ''
    }
    updateData(data){
        this.env.model.data = data;
        this.state.data = data;
        this.state.moves = this.state.data.moves.sort((a, b) => b.product_name.localeCompare(a.product_name));
        this.lines = this.state.data.move_lines.filter((x) => x.move_id === line.move_id);
        this.state.lines = this.lines;

    
        this.updateButton();
    
      }
    updateButton() {
        this.state.showNewProduct = false
        this.state.showSave = false
        this.state.showValidate = false
        this.state.finished = false;
        this.state.finished_message = '';

        this.state.showPackMulti = false;
        this.state.order_state = this.state.data.state
        this.state.total_lines = this.state.lines.length
        this.state.scanned_lines = this.state.lines.filter(x => x.picked).length
        if(this.state.data.state == 'done')
        {
            this.state.finished = true;
            this.state.finished_message = _t("Completed");  
        }
        else if(this.state.data.state == 'cancel')
        {
            this.state.finished = true;
            this.state.finished_message = _t("Cancelled");  
        }
        else
        {
            if (this.state.view === "Move") {
                this.state.detailTitle = this.state.data.name;
                if (!["done", "cancel"].includes(this.state.data.state)) {
                    if (this.state.activeTab === "OrderOverview") {
                        const hasLines = this.state.data.move_lines.length > 0;
                        const hasMoves = this.state.data.moves.length > 0;
            
                        const lineCond = this.requiredAllMoveLinePicked
                            ? (hasLines && this.state.data.move_lines.every(l => l.picked))
                            : this.state.data.move_lines.some(l => l.picked);
            
                        const moveCond = this.requiredAllMoveDone
                            ? (hasMoves && this.state.data.moves.every(m => Number(m.quantity || 0) >= Number(m.product_uom_qty || 0)))
                            : this.state.data.moves.some(m => Number(m.quantity || 0) >= Number(m.product_uom_qty || 0));
            
                        this.state.showValidate = !!(lineCond && moveCond);
            
                        // Cho phép xác nhận thiếu chỉ khi KHÔNG bắt buộc all_move_done
                        if (this.allowConfirmLackOrder && this.state.data.moves.length) {
                            // không thêm gì – block phía trên đã bao trùm
                        }
                    }
                    if (this.state.activeTab === "OrderDetail") {
                        // Ẩn nút "New Product" nếu bắt buộc quét sản phẩm
                        this.state.showNewProduct = !this.cfg.scan_product;
                    }
                    if (this.state.activeTab === "Packages") {
                        this.state.showPackMulti = true;
                    }
                }
            }
            
            if (this.state.view === "Move_line") {
                if (this.state.detailMoveLine.product_tracking != 'none') {
                    if (this.state.detailMoveLine.location_dest_id &&
                        this.state.detailMoveLine.location_id &&
                        (this.state.detailMoveLine.lot_id || this.state.detailMoveLine.lot_name) &&
                        this.state.detailMoveLine.quantity
                    ) {
                        this.state.showSave = true
                    }
                }
                else {
                    if (this.state.detailMoveLine.location_dest_id &&
                        this.state.detailMoveLine.location_id &&
                        this.state.detailMoveLine.quantity
                    ) {
                        this.state.showSave = true
                    }
                }
                const requiredScansOk =
                (!this.cfg.scan_source_location || this.scanned.source) &&
                (!this.cfg.scan_destination_location || this.scanned.dest) &&
                (!this.cfg.scan_lot || this.state.detailMoveLine.product_tracking === "none" || this.scanned.lot) &&
                (!this.cfg.scan_package || this.scanned.package || this.state.detailMoveLine.package_id || this.state.detailMoveLine.result_package_id);
        
                this.state.showSave = this.state.showSave && requiredScansOk; // ★ NEW
            }
        }
        
    }
    select(id) {

        this.state.selectedMove = id

        if (this.state.move === "Move") {
            this.state.move = "Move_line";
        } else if (this.state.move === "Move_line") {
            this.state.move = "Move";
        }
        this.focusCompute()
    }

    async exit(ev) {
        if (this.state.view === "Move") {
            //   await this.env.model.save();
            if (this.env.config.breadcrumbs.length > 1) {
                this.env.config.historyBack();
            }
            else {
                this.home.toggle(true)
            }
        } else {
            //this.toggleBarcodeLines();
            this.state.moves = this.state.data.moves.sort((a, b) => b.product_name.localeCompare(a.product_name));
            this.state.view = "Move"
            this.state.scannedLine = false
            this.updateButton()
        }
    }

    async onBarcodeScanned(barcode) {
        if (barcode) {
            const normalized = barcode.replace(/[\s,;|]+/gu, '\n').trim();
            const lines2 = normalized.split('\n').filter(Boolean);
            for (var line of lines2){
                await this.processBarcode(line, this.picking_id)
            }
            if ("vibrate" in window.navigator) {
                window.navigator.vibrate(100);
            }
        } else {
            const message = _t("Please, Scan again!");
            this.notification.add(message, { type: "warning" });
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

            }
        });
    }

    //--------------------------------------------------------------------------
    // Public
    //--------------------------------------------------------------------------

    keyClick = (option) => {
        option = option.toString();
        if (!this.state.detailMoveLine.quantity) {
            this.state.detailMoveLine.quantity = 0

        }
        if (option == "cancel") {
            this.state.showKeypad = false;
        }
        else if (option == "confirm") {
            this.state.showKeypad = false;
            this.updateButton()
        }
        else if (option == "DEL") {
            this.state.detailMoveLine.quantity = '0';
        }
        else if (option == "C") {
            var string = this.state.detailMoveLine.quantity.toString();

            this.state.detailMoveLine.quantity = string.substring(0, string.length - 1);
        }
        else if (option.includes('++')) {
            this.state.detailMoveLine.quantity = this.state.detailMoveLine.quantity_need.toString()
        }
        else if (option.includes('+')) {
            this.state.detailMoveLine.quantity = (parseFloat(this.state.detailMoveLine.quantity) + 1).toString();
        }
        else if (option.includes('-')) {
            this.state.detailMoveLine.quantity = (parseFloat(this.state.detailMoveLine.quantity) - 1).toString();
        }
        else {
            if (!(this.state.detailMoveLine.quantity.toString().includes('.') && option == '.'))
                if (this.state.detailMoveLine.quantity != 0)
                    this.state.detailMoveLine.quantity = this.state.detailMoveLine.quantity.toString() + option
                else
                    this.state.detailMoveLine.quantity = option
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
    async checkSerialNumber(serial_id) {
        const rec = await this.orm.call('stock.picking', 'check_serial_number', [,serial_id], {});
        return rec;
    }
    async processBarcode(barcode, picking_id) {
        if (this.state.isSelector) {
            if (this.state.view == "Move") {
                var barcodeData = await this.orm.call('stock.picking', 'get_barcode_data', [,barcode,false,false],{});
                //console.log(barcodeData)
                if (barcodeData.match) {
                    if (barcodeData.barcodeType == "products") {
                        if (barcodeData.fromCache) {
                            var move = this.state.data.moves.find(x => x.product_id == barcodeData.record.id)
                            this.state.selectedMove = move.id
                        }
                        else {
                            var product_id = barcodeData.record.id
                            var name = barcodeData.record.display_name
                            var location_id = this.state.data.location_id
                            var location_dest_id = this.state.data.location_dest_id
                            var values = { picking_id, product_id, name, location_id, location_dest_id }
                            var data = await this.orm.call('stock.picking', 'create_move', [, picking_id, values], {});
                            this.state.data = data.data
                            this.state.moves = this.state.data.moves.sort((a, b) => b.product_name.localeCompare(a.product_name));
                            this.state.selectedMove = data.move_id
                            console.log(data)
                        }
                        this.scanned.product = true;
                    }
                    if (barcodeData.barcodeType == "packages") {
                        if (barcodeData.fromCache) {
                            for (var product of barcodeData.record.products) {
                               var move = this.state.data.moves.find(x => x.product_id == product.product_id)
                               this.state.selectedMove = move.id
                            }
                        }
                        else {
                            if ((this.state.data.state != 'done' && this.state.data.state != 'cancel')) {
                                if (this.state.data.picking_type_code != "incoming") {
                                    // if(await this.orm.call('stock.picking', 'check_package_location', [,barcodeData.record.id,this.state.data.location_id],{})) 
                                    // {
                                        var values = {}
                                        for (var product of barcodeData.record.products) {
                                            
                                            values.product_id = product.product_id
                                            values.product_uom_id = product.product_uom_id
                                            values.location_id = product.location_id
                                            values.location_dest_id = this.state.data.location_dest_id
                                            values.lot_id = product.lot_id
                                            values.lot_name = false
                                            values.package_id = barcodeData.record.id
                                            values.result_package_id = barcodeData.record.id
                                            values.quantity = product.available_quantity
                                            values.picked = true
                                            values.picking_id = this.picking_id
                                            values.id = false
                                            values.move_id = false
                                            var data = await this.orm.call('stock.picking', 'save_data', [, picking_id, values,this.batch_id], {});
                                            this.state.data = data
                                            this.state.moves = this.state.data.moves.sort((a, b) => b.product_name.localeCompare(a.product_name));
                                        }
                                    // }
                                    // else{
                                    //     const message = _t(`${barcode}: Không đang ở vị trí ${this.state.data.location_name} !`);
                                    //     this.notification.add(message, { type: "warning" });
                                    // }
                                    
                                }
                                else{
                                    var line_incoming = this.state.data.move_lines.find(x=>x.result_package_id == barcodeData.record.id)
                                    var move_incoming = this.state.moves.find(x=>x.id == line_incoming.move_id) 
                                    if(move_incoming){
                                        this.editMove(move_incoming.id)
                                    }
                                    else{
                                        const message = _t(`This destination package: ${barcode} is not in the list!`);
                                        this.notification.add(message, { type: "warning" });
                                    }
                                }
                            }
                            else{
                                const message = _t(`Order completed, cannot add products to order !`);
                                this.notification.add(message, { type: "warning" });
                            }
                        }
                    }
                    if(barcodeData.barcodeType == "lots"){
                       
                        if ((this.state.data.state != 'done' && this.state.data.state != 'cancel')) {
                            if (this.state.data.picking_type_code != "incoming") {
                                let quants = await this.orm.searchRead('stock.quant', [['lot_id','=',barcodeData.record.id],['location_id.usage','=','internal']], ['id', 'available_quantity','package_id','location_id','product_id','product_uom_id']);
                                if (quants){
                                    for (var quant of quants){
                                        if(quant.available_quantity >0){
                                            var values = {}                                      
                                            values.product_id = quant.product_id[0]
                                            values.product_uom_id = quant.product_uom_id[0]
                                            values.location_id =  quant.location_id[0]
                                            values.location_dest_id = this.state.data.location_dest_id
                                            values.lot_id = barcodeData.record.id
                                            values.lot_name = barcode
                                            values.package_id = quant.package_id[0]
                                       
                                            values.quantity = quant.available_quantity
                                            values.picked = true
                                            values.picking_id = this.picking_id
                                            values.id = false
                                            values.move_id = false
                                            var data = await this.orm.call('stock.picking', 'save_data', [, picking_id, values,this.batch_id], {});
                                            this.state.data = data
                                            this.state.moves = this.state.data.moves.sort((a, b) => b.product_name.localeCompare(a.product_name));
                                        }
                                        
                                    }
                                    
                                }
                               
                                else{
                                    const message = _t(`${barcode}: Not available in stock !`);
                                    this.notification.add(message, { type: "warning" });
                                }
                                
                            }
                            else{ 
                                var exist_lot = await this.checkSerialNumber(barcodeData.record.id)
                                if(exist_lot){
                                    const message = _t(`Lot/serial number ${barcode} is already in the system!`);
                                    this.notification.add(message, { type: "warning" });
                                } 

                                else{
                                    var values = {}
                                    values.product_id = barcodeData.record.product_id
                                    values.product_uom_id = barcodeData.record.product_uom_id
                                    values.location_id = barcodeData.record.location_id
                                    values.location_dest_id = this.state.data.location_dest_id
                                    values.lot_id = barcodeData.record.id
                                    values.lot_name = barcode
                                    values.package_id = false
                                    values.result_package_id = false
                                    values.quantity = 1
                                    values.picked = true
                                    values.picking_id = this.picking_id
                                    values.id = false
                                    values.move_id = false
                                    var data = await this.orm.call('stock.picking', 'save_data', [, picking_id, values,this.batch_id], {});
                                    this.state.data = data
                                    this.state.moves = this.state.data.moves.sort((a, b) => b.product_name.localeCompare(a.product_name));
                                }
                            }
                        }
                        else{
                            const message = _t(`Order completed, cannot add products to order !`);
                            this.notification.add(message, { type: "warning" });
                        }

                    }
                }
                else {
                    const message = _t(`No barcode information found: ${barcode}!`);
                    this.notification.add(message, { type: "warning" });
                }
            }
            if (this.state.view == "Move_line") {                
                var barcodeData = await this.orm.call('stock.picking', 'get_barcode_data', [,barcode,{'product_id':this.state.detailMoveLine.product_id},false],{});
                if(this.state.focus == 0)
                {
                    if(barcodeData.match){
                        if(barcodeData.barcodeType == "packages" ) //Xử lý package Nguồn
                        {
                            if(this.state.scannedLine && this.state.scannedLine?.package_id !=barcodeData.record.id)
                            {
                                console.log(this.state.scannedLine)
                                if(this.state.scannedLine.result_package_name == barcodeData.barcode){
                                    var data = await this.orm.call('stock.picking', 'save_data', [, this.picking_id, this.state.scannedLine,this.batch_id], {});
                                    this.state.data = data
                                    this.editMove(this.state.detailMoveLine.move_id)
                                    this.state.scannedLine = false
                                }
                                else{
                                    const message = _t(`This destination packet: ${barcode} is invalid!`);
                                    this.notification.add(message, { type: "warning" });
                                }
                                
                            }
                            else{
                                if (this.state.data.picking_type_code != "incoming") {
                                    if (this.state.detailMoveLine.location_id == barcodeData.record.location)
                                    {
                                        for(var prod of barcodeData.record.products.filter(x=>x.product_id == this.state.detailMoveLine.product_id))
                                        {
                                            if(this.allowGetFullPackage)
                                            {
                                                if(this.state.detailMoveLine.id)
                                                {
                                                    if(prod.product_id == this.state.detailMoveLine.product_id)
                                                    {
                                                        //console.log({prod,lots:this.props.lots})
                                                        var lot =  await this.orm.searchRead('stock.lot',[['product_id','=',prod.product_id],['expiration_date','<',prod.expiration_date]], ['name'])
                                                        if(lot){
                                                            const message = _t(`Lot number: ${prod.lot_name} has an expiration date greater than the expiration date of lot: ${lot.name}!`);
                                                            this.notification.add(message, { type: "warning" });
                                                        }
                                                        if(this.state.detailMoveLine.lot_id)
                                                        {
                                                            if(prod.lot_id == this.state.detailMoveLine.lot_id)
                                                            {
                                                                var quantity = this.state.detailMoveLine.quantity_need + this.state.detailMoveLine.quantity
                                                                this.state.detailMoveLine.quantity = prod.quantity > quantity ? quantity : prod.quantity
                                                                this.state.detailMoveLine.package_id = barcodeData.record.id
                                                                if(!this.state.detailMoveLine.result_package_id){
                                                                    this.state.detailMoveLine.result_package_id = prod.quantity <= quantity ? barcodeData.record.id : false
                                                                }
                                                                this.state.detailMoveLine.location_id = prod.location_id
                                                                var data = await this.orm.call('stock.picking', 'save_data', [, this.picking_id, this.state.detailMoveLine,this.batch_id], {});
                                                                this.state.data = data
                                                                this.editMove(this.state.detailMoveLine.move_id)
                                                                
                                                            }
                                                            
                                                        }
                                                        else{
                                                            var quantity = this.state.detailMoveLine.quantity_need + this.state.detailMoveLine.quantity
                                                            this.state.detailMoveLine.quantity = prod.quantity > quantity ? quantity : prod.quantity
                                                            this.state.detailMoveLine.package_id = barcodeData.record.id
                                                            if(!this.state.detailMoveLine.result_package_id){
                                                                this.state.detailMoveLine.result_package_id = prod.quantity <= quantity ? barcodeData.record.id : false
                                                            }
                                                            this.state.detailMoveLine.location_id = prod.location_id
                                                            this.state.detailMoveLine.lot_id = prod.lot_id
                                                            this.state.detailMoveLine.lot_name =false
                                                            var data = await this.orm.call('stock.picking', 'save_data', [, this.picking_id, this.state.detailMoveLine,this.batch_id], {});
                                                            this.state.data = data
                                                            this.editMove(this.state.detailMoveLine.move_id)
                                                        }
                                                    }
                                                }
                                                else
                                                {

                                                        var lot = await this.orm.searchRead('stock.lot',[['product_id','=',prod.product_id],['expiration_date','<',prod.expiration_date]], ['name'])
                                                        if(lot){
                                                            const message = _t(`Lot number: ${prod.lot_name} has an expiration date greater than the expiration date of lot: ${lot.name}!`);
                                                            this.notification.add(message, { type: "warning" });
                                                        }
                                                    var line = this.lines.find(x=>x.package_id == barcodeData.record.id && x.lot_id == prod.lot_id)
                                                    // console.log({line,lines:this.lines,record:barcodeData.record})
                                                    if (line)
                                                    {
                                                        var quantity = this.state.detailMoveLine.quantity_need + line.quantity
                                                        line.quantity = prod.quantity > quantity ? quantity : prod.quantity
                                                        line.lot_id = prod.lot_id
                                                        line.lot_name =false
                                                        line.package_id = barcodeData.record.id
                                                        line.package_name = barcodeData.record.name
                                                        if(!line.result_package_id){
                                                            line.result_package_id = prod.quantity <= quantity ? barcodeData.record.id : false
                                                        }
                                                        line.location_id = prod.location_id
            
                                                        if(
                                                            line.result_package_name?.includes("MOVE") && !line.package_name?.includes("MOVE")||
                                                            (line.result_package_name?.includes("CUT") && !line.package_name?.includes("CUT"))
                                                        ){
                                                            this.state.scannedLine = line
                                                        }
                                                        else{
                                                            var data = await this.orm.call('stock.picking', 'save_data', [, this.picking_id, line,this.batch_id], {});
                                                            this.state.data = data
                                                            this.editMove(this.state.detailMoveLine.move_id)
                                                        }
                                                        
                                                       
                                                        
                                                      
                                                    }
                                                    else
                                                    {
                                                        var quantity = this.state.detailMoveLine.quantity_need
                                                        this.state.detailMoveLine.quantity = prod.quantity > quantity ? quantity : prod.quantity
                                                        this.state.detailMoveLine.lot_id = prod.lot_id
                                                        this.state.detailMoveLine.lot_name =''
                                                        this.state.detailMoveLine.package_id = barcodeData.record.id
                                                        this.state.detailMoveLine.package_name = barcodeData.record.name
                                                        if(!this.state.detailMoveLine.result_package_id){
                                                            this.state.detailMoveLine.result_package_id = prod.quantity <= quantity ? barcodeData.record.id : false
                                                        }
                                                        this.state.detailMoveLine.location_id = prod.location_id
            
                                                        this.save()
                                                    }
                                                }
                                            }
                                            else{
                                                if(prod.available_quantity > 0)
                                                {
                                                    if(this.state.detailMoveLine.id)
                                                    {
                                                        if(prod.product_id == this.state.detailMoveLine.product_id)
                                                        {
                                                            if(this.state.detailMoveLine.lot_id)
                                                            {
                                                                if(prod.lot_id == this.state.detailMoveLine.lot_id)
                                                                {
                                                                    var quantity = this.state.detailMoveLine.quantity_need + this.state.detailMoveLine.quantity
                                                                    this.state.detailMoveLine.quantity = prod.available_quantity > this.state.detailMoveLine.quantity_need ? quantity : prod.available_quantity + this.state.detailMoveLine.quantity
                                                                    this.state.detailMoveLine.package_id = barcodeData.record.id
                                                                    if(!this.state.detailMoveLine.result_package_id && prod.available_quantity == prod.quantity){
                                                                        this.state.detailMoveLine.result_package_id = prod.available_quantity <= this.state.detailMoveLine.quantity_need ? barcodeData.record.id : false
                                                                    }
                                                                    this.state.detailMoveLine.location_id = prod.location_id
                                                                    var data = await this.orm.call('stock.picking', 'save_data', [, this.picking_id, this.state.detailMoveLine,this.batch_id], {});
                                                                    this.state.data = data
                                                                    this.editMove(this.state.detailMoveLine.move_id)
                                                                    
                                                                }
                                                            }
                                                            else{
                                                                var quantity = this.state.detailMoveLine.quantity_need + this.state.detailMoveLine.quantity
                                                                this.state.detailMoveLine.quantity = prod.available_quantity > this.state.detailMoveLine.quantity_need ? quantity : prod.available_quantity + this.state.detailMoveLine.quantity
                                                                this.state.detailMoveLine.package_id = barcodeData.record.id
                                                                if(!this.state.detailMoveLine.result_package_id && prod.available_quantity == prod.quantity){
                                                                    this.state.detailMoveLine.result_package_id = prod.available_quantity <= this.state.detailMoveLine.quantity_need  ? barcodeData.record.id : false
                                                                }
                                                                this.state.detailMoveLine.location_id = prod.location_id
                                                                this.state.detailMoveLine.lot_id = prod.lot_id
                                                                this.state.detailMoveLine.lot_name =false
                                                                var data = await this.orm.call('stock.picking', 'save_data', [, this.picking_id, this.state.detailMoveLine,this.batch_id], {});
                                                                this.state.data = data
                                                                this.editMove(this.state.detailMoveLine.move_id)
                                                            }
                                                        }
                                                    }
                                                    else
                                                    {
                                                        var line = this.lines.find(x=>x.package_id == barcodeData.record.id && x.lot_id == prod.lot_id)
                                                        console.log({line,lines:this.lines,record:barcodeData.record})
                                                        if (line)
                                                        {
                                                            var quantity = this.state.detailMoveLine.quantity_need + line.quantity
                                                            line.quantity = prod.available_quantity > this.state.detailMoveLine.quantity_need ? quantity : prod.available_quantity + line.quantity
                                                            line.lot_id = prod.lot_id
                                                            line.lot_name =false
                                                            line.package_id = barcodeData.record.id
                                                            line.package_name = barcodeData.record.name
                                                            if(!line.result_package_id && prod.available_quantity == prod.quantity){
                                                                line.result_package_id = prod.available_quantity <= this.state.detailMoveLine.quantity_need ? barcodeData.record.id : false
                                                            }
                                                            line.location_id = prod.location_id
                                                            console.log({'prod':prod,line})
                                                            var data = await this.orm.call('stock.picking', 'save_data', [, this.picking_id, line,this.batch_id], {});
                                                            this.state.data = data
                                                            this.editMove(this.state.detailMoveLine.move_id)
                                                            //console.log({'detailMoveLine':this.state.detailMoveLine,'prod':prod,line})
                                                        }
                                                        else
                                                        {
                                                            var quantity = this.state.detailMoveLine.quantity_need
                                                            this.state.detailMoveLine.quantity = prod.available_quantity > quantity ? quantity : prod.available_quantity
                                                            this.state.detailMoveLine.lot_id = prod.lot_id
                                                            this.state.detailMoveLine.lot_name =''
                                                            this.state.detailMoveLine.package_id = barcodeData.record.id
                                                            this.state.detailMoveLine.package_name = barcodeData.record.name
                                                            if(!this.state.detailMoveLine.result_package_id && prod.available_quantity == prod.quantity){
                                                                this.state.detailMoveLine.result_package_id = prod.available_quantity <= this.state.detailMoveLine.quantity_need ? barcodeData.record.id : false
                                                            }
                                                            this.state.detailMoveLine.location_id = prod.location_id
                                                            //console.log({'detailMoveLine':this.state.detailMoveLine,'prod':prod})
                                                            this.save()
                                                        }
                                                    }
                                                }
                                                else{
                                                    const message = _t(`Package: "${barcode}" is no longer available in sufficient quantity`);
                                                    this.notification.add(message, { type: "warning" });
                                                }
                                            }
            
                                            
                                            
                                            
                                        }
                                    }
                                    else
                                    {
                                        const message = _t(`Package: "${barcode}" is not located at: "${this.state.detailMoveLine.location_name}". It is located at: "${barcodeData.record.location_name}"`);
                                        this.notification.add(message, { type: "warning" });
                                    }
                                    
                                }
                                else
                                {
                                    var incoming_line = this.state.lines.find(x=>x.result_package_id == barcodeData.record.id)
                                    if(incoming_line){
                                        var data = await this.orm.call('stock.picking', 'save_data', [, this.picking_id, incoming_line,this.batch_id], {});
                                        this.state.data = data
                                        this.editMove(this.state.detailMoveLine.move_id)
                                        
                                    }
                                    else{
                                        const message = _t(`This destination package: ${barcode} is not in the list!`);
                                        this.notification.add(message, { type: "warning" });
                                    }
                                }
                            }
                            this.scanned.package = true; // ★ NEW

                        }
                        else if(barcodeData.barcodeType == "lots" && barcodeData.record.product_id == this.state.detailMoveLine.product_id){
                            if(this.state.detailMoveLine.product_tracking == "lot"){
                                this.state.detailMoveLine.lot_name = barcodeData.barcode
                                this.state.detailMoveLine.lot_id = barcodeData.record.id
                                this.state.detailMoveLine.quantity += 1
                            }
                            else if(this.state.detailMoveLine.product_tracking == "serial"){
                                let line_serial = this.state.lines.find(x=>x.lot_name == barcode)
                                if(line_serial){
                                    var data = await this.orm.call('stock.picking', 'save_data', [, this.picking_id, line_serial,this.batch_id], {});
                                    this.state.data = data
                                    this.editMove(this.state.detailMoveLine.move_id)
                                }
                                else{
                                    let quant = await this.orm.searchRead('stock.quant', [['lot_id','=',barcodeData.record.id],['location_id.usage','=','internal'],['available_quantity','>',0]], ['id', 'available_quantity','package_id','location_id']);
                                    if (quant){
                                        
                                        this.state.detailMoveLine.quantity = 1
                                        this.state.detailMoveLine.lot_id = barcodeData.record.id
                                        this.state.detailMoveLine.lot_name =''
                                        this.state.detailMoveLine.package_id = quant[0].package_id[0]
                                        this.state.detailMoveLine.package_name =  quant[0].package_id[1]
                                        
                                        this.state.detailMoveLine.location_id = quant[0].location_id[0]
    
                                        this.save()
                                    }
                                }
                            }
                            this.scanned.lot = true; // ★ NEW
                        }
                        else if(barcodeData.barcodeType == "locations"){
                            if(this.state.detailMoveLine.picking_type_code == 'incoming')
                            {
                                this.state.detailMoveLine.location_dest_id = barcodeData.record.id
                                this.state.detailMoveLine.location_dest_name = barcodeData.record.display_name
                                this.scanned.dest = true; // ★ NEW

                            }
                            else if(this.state.detailMoveLine.picking_type_code == 'outgoing')
                            {
                                this.state.detailMoveLine.location_id = barcodeData.record.id
                                this.state.detailMoveLine.location_name = barcodeData.record.display_name
                                this.scanned.source = true;
                            }
                            else
                            {
                                if(this.move.location_id == this.state.detailMoveLine.location_id)
                                {
                                    this.state.detailMoveLine.location_id = barcodeData.record.id
                                    this.state.detailMoveLine.location_name = barcodeData.record.display_name
                                    this.scanned.source = true;
                                }
                                else
                                {
                                    this.state.detailMoveLine.location_dest_id = barcodeData.record.id
                                    this.state.detailMoveLine.location_dest_name = barcodeData.record.display_name
                                    this.scanned.dest = true; // ★ NEW
                                }
                            }
    
                        }
                    }
                    else{
                        if(this.state.detailMoveLine.picking_type_code == 'incoming'){
                            let line_serial = this.state.lines.find(x=>x.lot_name == barcode)
                            if(line_serial){
                                var data = await this.orm.call('stock.picking', 'save_data', [, this.picking_id, line_serial,this.batch_id], {});
                                this.state.data = data
                                this.editMove(this.state.detailMoveLine.move_id)
                            }
                            else{ 
                                this.state.detailMoveLine.quantity = 1                              
                                this.state.detailMoveLine.lot_name =barcode          
                                this.save() 
                            }
                        }
                        
                        else{ 
                            const message = _t(`Barcode: "${barcode}" not found in the system!`);
                            this.notification.add(message, { type: "warning" });
                        }
                    }
                    
                }
                else if (this.state.focus == 1)
                {
                    if(!isNaN(Number(barcodeData.barcode)))
                    {
                        this.state.detailMoveLine.quantity= Number(barcodeData.barcode)
                    }
                    else
                    {
                        const message = _t(`Barcode: ${barcode} is not a number!`);
                        this.notification.add(message, { type: "warning" });
                    }
                }
                else if (this.state.focus == 2)
                {
                    if(barcodeData.barcodeType == "lots" || !barcodeData.barcodeType)
                    {
                        this.state.detailMoveLine.lot_name = barcode
                    }
                    else
                    {
                        const message = _t(`Barcode: ${barcode} is ${barcodeData.barcodeType} so it cannot be used!`);
                        this.notification.add(message, { type: "warning" });
                    }
                }
                else if (this.state.focus == 3)
                {
                    if(barcodeData.barcodeType == "locations")
                    {
                        this.state.detailMoveLine.location_id = barcodeData.record.id
                        this.state.detailMoveLine.location_name = barcodeData.record.display_name
                    }
                    else
                    {
                        const message = _t(`Barcode: ${barcode} is ${barcodeData.barcodeType} so it cannot be used!`);
                        this.notification.add(message, { type: "warning" });
                    }
                }
                else if (this.state.focus == 4)
                {
                    if(barcodeData.barcodeType == "locations")
                    {
                        this.state.detailMoveLine.location_dest_id = barcodeData.record.id
                        this.state.detailMoveLine.location_dest_name = barcodeData.record.display_name
                    }
                    else
                    {
                        const message = _t(`Barcode: ${barcode} is ${barcodeData.barcodeType} so it cannot be used!`);
                        this.notification.add(message, { type: "warning" });
                    }
                }
                else if (this.state.focus == 5)
                {
                    if(barcodeData.barcodeType == "packages")
                    {
                        this.state.detailMoveLine.package_id = barcodeData.record.id
                        this.state.detailMoveLine.package_name = barcodeData.record.name
                    } 
                }
                else if (this.state.focus == 6)
                {
                    console.log({barcodeData})
                    if(barcodeData.barcodeType == "packages" || !barcodeData.barcodeType)
                    {
                        if(this.state.showSave)
                        {
                            //console.log({barcodeData,state:this.state})
                            if(barcodeData.barcodeType == "packages")
                            {
                                this.state.detailMoveLine.result_package_id = barcodeData.record.id
                                this.state.detailMoveLine.result_package_name = barcodeData.record.name
                                this.save()
                            }
                            else
                            {
                                this.createPack(barcodeData.barcode)
                            }
                        }
                        else{
                            const message = _t(`Please update command parameters before closing the pack!`);
                            this.notification.add(message, { type: "warning" });
                        }
                        this.scanned.package = true; // ★ NEW

                    }
                    else
                    {
                        const message = _t(`Barcode: ${barcode} is ${barcodeData.barcodeType} so it cannot be used!`);
                        this.notification.add(message, { type: "warning" });
                    }
                }
                
            }
            this.updateButton()
        }
    }

}




registry.category("actions").add("smartbiz_barcode_picking_action", StockPicking);

export default StockPicking;
