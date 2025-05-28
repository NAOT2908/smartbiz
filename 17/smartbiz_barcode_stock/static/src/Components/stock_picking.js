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
import SmartBizBarcodePickingModel from "../Models/barcode_picking";
import { Component, EventBus, onPatched, onWillStart, useState, useSubEnv, xml } from "@odoo/owl";

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
    //--------------------------------------------------------------------------
    // Lifecycle
    //--------------------------------------------------------------------------

    setup() {
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
        this.state = useState({
            view: "Move", // Could be also 'printMenu' or 'editFormView'.
            displayNote: false,
            inputValue: "",
            moves: [],
            lines: [],
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
        });

        this.records = [];
        this.multiSelect = false;
        this.selectorTitle = '';

        //Cấu hình cho phép lấy hàng dự trữ từ đơn khác
        this.allowGetFullPackage = true;
        //Cấu hình yêu cầu tất cả các move phải hoàn thành
        this.requiredAllMoveDone = false;
         //Cấu hình cho phép xác nhận đơn thiếu
         this.allowConfirmLackOrder = true;
    }
    roundToTwo(num) {
        return Math.round(num * 100) / 100;
    }
    toggleMenu = () => {
        this.state.menuVisible = !this.state.menuVisible;
    }
    async initData()
    {
        var data = await this.orm.call('stock.picking', 'get_data', [,this.picking_id,this.batch_id], {});
        this.state.moves = data.moves.sort((a, b) => b.product_name.localeCompare(a.product_name));
        this.env.model.data = data
        this.updateButton()
        if(this.batch_id && data.moves.length == 0)
        {
            await this.createBatch(this.env.model.data.batch_picking_type_id)
        }
    }
    async createBatch(picking_type_id){
        if(picking_type_id)
        {
            this.clearSelector()
            this.records = await this.orm.searchRead("stock.picking", [['picking_type_id','=',picking_type_id],['batch_id','=',false],['state','not in',['done','draft','cancel']]], ["name","origin"]) 
            this.multiSelect = true
            this.selectorTitle = "Chọn điều chuyển"
            this.state.showSelector = true
            
        }
        else
        {
            this.records = await this.orm.searchRead("stock.picking.type", [], ["display_name"]) 
            this.multiSelect = false
            this.selectorTitle = "Chọn kiểu điều chuyển"
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
            this.state.moves = this.env.model.data.moves.sort((a, b) => b.product_name.localeCompare(a.product_name));
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
                this.state.moves = this.filterArrayByString(this.env.model.data.moves, this.state.searchInput).sort((a, b) => b.product_name.localeCompare(a.product_name));
            }
            if (this.state.view === 'Move_line') {
                this.state.lines = this.filterArrayByString(this.lines, this.state.searchInput)
            }
        }
        else {
            this.state.moves = this.env.model.data.moves.sort((a, b) => b.product_name.localeCompare(a.product_name));
            this.state.lines = this.lines
        }
    }
    changeTab(tab) { 
        this.state.activeTab = tab;
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
        this.env.model.data = await this.orm.call('stock.picking', 'save_data', [,this.picking_id, this.state.detailMoveLine,this.batch_id], {});
        this.state.moves = this.env.model.data.moves.sort((a, b) => b.product_name.localeCompare(a.product_name));
        this.lines = this.env.model.data.move_lines.filter(x => x.move_id === this.state.detailMoveLine.move_id)
        this.state.lines = this.lines
        var lot_id = this.state.detailMoveLine.lot_id
        var lot_name = this.state.detailMoveLine.lot_name
        this.editMove(this.state.detailMoveLine.move_id)
        this.state.detailMoveLine.lot_id = lot_id
        this.state.detailMoveLine.lot_name = lot_name
        this.focusCompute()

    }
    async doneMove(id) {
        this.env.model.data = await this.orm.call('stock.picking', 'done_move', [,this.picking_id, id,this.batch_id], {});
        this.state.moves = this.env.model.data.moves.sort((a, b) => b.product_name.localeCompare(a.product_name));
    }
    async doneMoveLine(id) {
        this.env.model.data = await this.orm.call('stock.picking', 'done_move_line', [,this.picking_id, id,this.batch_id], {});
        this.state.moves = this.env.model.data.moves.sort((a, b) => b.product_name.localeCompare(a.product_name));
    }
    async actionDone(id) {
        const params = {
            title: _t("Xác nhận đơn"),
            body: _t("Bạn có chắc chắn muốn xác nhận đơn này."),
            confirm: async () => {
                var res = await this.orm.call('stock.picking', 'barcode_action_done', [,this.picking_id,this.batch_id], {context:{skip_backorder: true,display_detailed_backorder: true}});
                if(res.action)
                {
                    res = await this.action.doAction(res.action)
                    console.log(res)
                }
                else
                {
                    this.env.model.data = res
                    this.state.moves = this.env.model.data.moves.sort((a, b) => b.product_name.localeCompare(a.product_name));
                    this.updateButton()
                }
            },
            cancel: () => { },
            confirmLabel: _t("Có, xác nhận."),
            cancelLabel: _t("Hủy bỏ"),
        };
        this.dialog.add(ConfirmationDialog, params);  
        
    }
    async cancelOrder() {
        this.state.menuVisible = false;
        const params = {
            title: _t("Xác nhận hủy đơn"),
            body: _t("Bạn có chắc chắn muốn hủy đơn này."),
            confirm: async () => {
                var res = await this.orm.call('stock.picking', 'cancel_order', [,this.picking_id,this.batch_id],{});
                this.env.model.data = res
                this.state.moves = this.env.model.data.moves.sort((a, b) => b.product_name.localeCompare(a.product_name));
                this.updateButton()
                
            },
            cancel: () => { },
            confirmLabel: _t("Có, xác nhận."),
            cancelLabel: _t("Hủy bỏ"),
        };
        this.dialog.add(ConfirmationDialog, params);  
        
    }
    
    async createPack(package_name=false) {
        var data = await this.orm.call('stock.picking', 'create_pack', [,this.picking_id, this.state.detailMoveLine, package_name,this.batch_id], {});       
        var line =  data.move_lines.find(aItem => !(this.env.model.data.move_lines.some(bItem => bItem.id === aItem.id)) )
        this.env.model.data = data
        this.state.moves = this.env.model.data.moves.sort((a, b) => b.product_name.localeCompare(a.product_name));
        this.lines = this.env.model.data.move_lines.filter(x => x.move_id === this.state.detailMoveLine.move_id)
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
            title: _t("Xác nhận xóa"),
            body: _t("Bạn có chắc chắn muốn xóa dòng di chuyển này không? Thao tác này không thể hoàn tác."),
            confirm: async () => {
                this.env.model.data = await this.orm.call('stock.picking', 'delete_move_line', [,this.picking_id, id,this.batch_id], {});
                this.state.moves = this.env.model.data.moves.sort((a, b) => b.product_name.localeCompare(a.product_name));

                this.lines = this.env.model.data.move_lines.filter(x => x.move_id === this.state.detailMoveLine.move_id);
                this.state.lines = this.lines;
                var lot_id = this.state.detailMoveLine.lot_id;
                var lot_name = this.state.detailMoveLine.lot_name;
                this.editMove(this.state.detailMoveLine.move_id);
                this.state.detailMoveLine.lot_id = lot_id;
                this.state.detailMoveLine.lot_name = lot_name;
                this.updateButton()
            },
            cancel: () => { },
            confirmLabel: _t("Có, xóa nó"),
            cancelLabel: _t("Hủy bỏ"),
        };
        this.dialog.add(ConfirmationDialog, params);
    }
    async deleteMove(id) {
        const params = {
            title: _t("Xác nhận xóa"),
            body: _t("Bạn có chắc chắn muốn xóa dòng di chuyển này không? Thao tác này không thể hoàn tác."),
            confirm: async () => {
                this.env.model.data = await this.orm.call('stock.picking', 'delete_move', [,this.picking_id, id,this.batch_id], {});
                this.state.moves = this.env.model.data.moves.sort((a, b) => b.product_name.localeCompare(a.product_name));
                this.updateButton()
      
            },
            cancel: () => { },
            confirmLabel: _t("Có, xóa nó"),
            cancelLabel: _t("Hủy bỏ"),
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
        this.move = this.env.model.data.moves.find(x => x.id === id)
        var move = this.move;
        this.state.detailTitle = this.move.picking_name
        this.picking_id = this.move.picking_id
        this.state.search = false;
        this.state.searchInput = '';
        this.lines = this.env.model.data.move_lines.filter(x => x.move_id === id)
        this.state.lines = this.lines
        var location_id = this.state?.detailMoveLine?.location_id ? this.state.detailMoveLine.location_id : move.location_id
        var location_name = this.state?.detailMoveLine?.location_id ? this.state.detailMoveLine.location_name : move.location_name
        var lot_id = this.state?.detailMoveLine?.lot_id ? this.state.detailMoveLine.lot_id : false
        var lot_name = this.state?.detailMoveLine?.lot_id ? this.state.detailMoveLine.lot_name : this.env.model.data.lot_name
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

    openSelector(option) {
        if (option == 1) {
            //Open create packages
            this.state.isSelector = false;
            this.state.menuVisible = false;
            this.selectorTitle = "Chia tách Packages";
        }
        if (option == 8) {
            //Đóng nhiều packge một lúc
            this.state.isSelector = false;
            this.state.menuVisible = false;
            this.selectorTitle = "Đóng Packages loạt";
        }
        if (option == 9) {
            //Nhận theo số sê-ri
            this.state.isSelector = false;
            this.state.menuVisible = false;
            this.records = this.state.lines;
            this.selectorTitle = "Nhận theo số sê-ri";
        }
        if (option == 2)//Chọn số Lot
        {
            this.records = this.env.model.data.lots.filter(x => x.product_id[0] == this.move.product_id)
            this.multiSelect = false
            this.selectorTitle = "Chọn số Lô/Sê-ri"
        }
        if (option == 3)//Chọn vị trí nguồn
        {
            this.records = this.env.model.data.locations
            this.multiSelect = false
            this.selectorTitle = "Chọn vị trí nguồn"
        }
        if (option == 4)//Chọn vị trí đích
        {
            this.records = this.env.model.data.locations
            this.multiSelect = false
            this.selectorTitle = "Chọn vị trí đích"
        }
        if (option == 5)//Chọn gói nguồn
        {
            this.records = this.env.model.data.packages
            this.multiSelect = false
            this.selectorTitle = "Chọn kiện nguồn"
        }
        if (option == 6)//Chọn gói đích
        {
            this.records = this.env.model.data.packages
            this.multiSelect = false
            this.selectorTitle = "Chọn kiện đích"
        }
        this.state.showSelector = true

    }
    async newProduct(){
        this.records = await this.orm.searchRead("product.product", [], ["display_name"]) 
        this.multiSelect = false
        this.selectorTitle = "Chọn sản phẩm"
        this.state.showSelector = true
    }
    clearSelector() {
        this.records = []
        this.multiSelect = false
        this.selectorTitle = ""
        this.state.showSelector = false;
        this.state.isSelector = true;
        this.updateButton()
    }
    async closeSelector(data){
        if (data) {
            if (this.selectorTitle == "Chia tách Packages") {
                for (var line of data) {
                    //console.log(line)
                    this.env.model.data = await this.orm.call(
                        "stock.picking",
                        "save_data",
                        [, this.picking_id, line, this.batch_id],
                        {}
                    );
                    this.state.moves = this.env.model.data.moves.sort((a, b) => b.product_name.localeCompare(a.product_name));
                    this.lines = this.env.model.data.move_lines.filter((x) => x.move_id === line.move_id);
                    this.state.lines = this.lines;
                }
                this.clearSelector();
            }
            if (this.selectorTitle == "Đóng Packages loạt") {
                for (var line of data) {
                    //console.log(line)
                    this.env.model.data = await this.orm.call(
                        "stock.picking",
                        "save_data",
                        [, this.picking_id, line, this.batch_id],
                        {}
                    );
                    this.state.moves = this.env.model.data.moves.sort((a, b) => b.product_name.localeCompare(a.product_name));
                    this.lines = this.env.model.data.move_lines.filter((x) => x.move_id === line.move_id);
                    this.state.lines = this.lines;
                }
                this.clearSelector();
            }
            if (this.selectorTitle == "Nhận theo số sê-ri") {
                for (var line of data) {
                    //console.log(line)
                    this.env.model.data = await this.orm.call(
                        "stock.picking",
                        "save_data",
                        [, this.picking_id, line, this.batch_id],
                        {}
                    );
                    this.state.moves = this.env.model.data.moves.sort((a, b) => b.product_name.localeCompare(a.product_name));
                    this.lines = this.env.model.data.move_lines.filter((x) => x.move_id === line.move_id);
                    this.state.lines = this.lines;
                }
                this.clearSelector();
            }
            if (this.selectorTitle == "Chọn số Lô/Sê-ri") {
                if (data.id) {
                    this.state.detailMoveLine.lot_id = data.id
                    this.state.detailMoveLine.lot_name = data.name
                    this.clearSelector()
                }
                else {
                    this.state.detailMoveLine.lot_id = false
                    this.state.detailMoveLine.lot_name = data
                    this.clearSelector()
                }

            }
            if (this.selectorTitle == "Chọn vị trí nguồn") {
                this.state.detailMoveLine.location_id = data.id
                this.state.detailMoveLine.location_name = data.display_name
                this.clearSelector()
            }
            if (this.selectorTitle == "Chọn vị trí đích") {
                this.state.detailMoveLine.location_dest_id = data.id
                this.state.detailMoveLine.location_dest_name = data.display_name
                this.clearSelector()
            }
            if (this.selectorTitle == "Chọn kiện nguồn") {
                this.state.detailMoveLine.package_id = data.id
                this.state.detailMoveLine.package_name = data.name
                this.clearSelector()
            }
            if (this.selectorTitle == "Chọn kiện đích") {
                if (data.id){
                    this.state.detailMoveLine.result_package_id = data.id
                    this.state.detailMoveLine.result_package_name = data.name
                    this.clearSelector()
                }
                else{
                    await this.createPack(data)
                    this.clearSelector()
                }
                
            }
            if (this.selectorTitle == "Chọn sản phẩm") {
                var product_id = data.product_id
                var name = data.display_name
                var product_uom_qty = data.quantity || 0
                var location_id = this.env.model.data.location_id
                var location_dest_id = this.env.model.data.location_dest_id
                var values = { picking_id:this.picking_id, product_id, name, location_id, location_dest_id ,product_uom_qty}
                var data = await this.orm.call('stock.picking', 'create_move', [, this.picking_id, values,this.batch_id], {});
                this.env.model.data = data.data
                this.state.moves = this.env.model.data.moves.sort((a, b) => b.product_name.localeCompare(a.product_name));
                this.state.selectedMove = data.move_id
                this.clearSelector()
            }
            
            if (this.selectorTitle == "Chọn điều chuyển") {
                
                var values = { picking_ids:data,state:'in_progress'}
                console.log(values)
                this.env.model.data = await this.orm.call('stock.picking', 'update_batch_picking', [, this.picking_id, values,this.batch_id], {});
                this.state.moves = this.env.model.data.moves.sort((a, b) => b.product_name.localeCompare(a.product_name));
                this.clearSelector()
                
            }
            if (this.selectorTitle == "Chọn kiểu điều chuyển") {
                console.log({data})
                await this.createBatch(data.id)

            }
        }
        else
        {
            this.clearSelector()
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
            if (this.env.model.data.state === "done"){
                cl += " s_footer_done";
            }
        }
        return cl;
    }
    updateButton() {
        this.state.showNewProduct = false
        this.state.showSave = false
        this.state.showValidate = false
        this.state.finished = false;
        this.state.finished_message = '';
        this.state.order_state = this.env.model.data.state
        if(this.env.model.data.state == 'done')
        {
            this.state.finished = true;
            this.state.finished_message = 'Đã hoàn tất';
        }
        else if(this.env.model.data.state == 'cancel')
        {
            this.state.finished = true;
            this.state.finished_message = 'Đã bị hủy';
        }
        else
        {
            if (this.state.view === "Move") {
                this.state.detailTitle = this.env.model.data.name
                if (!['done','cancel'].includes(this.env.model.data.state) ) {
                    if (this.requiredAllMoveDone){
                        const allMoveLinesPicked = this.env.model.data.move_lines.every(line => line.picked);
                        const allDone = this.env.model.data.moves.every(move => move.quantity >= move.product_uom_qty);
                        if(this.env.model.data.moves.length && allMoveLinesPicked && allDone)
                        {
                            this.state.showValidate = true
                        }
                    }
                    else{
                        const someMoveLinesPicked = this.env.model.data.move_lines.some(line => line.picked);
                        const someDone = this.env.model.data.moves.some(move => move.quantity >= move.product_uom_qty);
                        if(this.env.model.data.moves.length && someMoveLinesPicked && someDone)
                        {
                            this.state.showValidate = true
                        }
                    }
                    if(this.allowConfirmLackOrder)
                    {
                        const allMoveLinesPicked = this.env.model.data.move_lines.every(line => line.picked);
                        if(this.env.model.data.moves.length && allMoveLinesPicked)
                            {
                                this.state.showValidate = true
                            }
                    }
                        
                    this.state.showNewProduct = true
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
            this.state.moves = this.env.model.data.moves.sort((a, b) => b.product_name.localeCompare(a.product_name));
            this.state.view = "Move"
            this.state.scannedLine = false
            this.updateButton()
        }
    }
    containsLineBreak(text, {full = false} = {}) {
        return full
          ? /\r\n|[\n\r\u2028\u2029]/.test(text)   // kiểm tra toàn diện
          : /\r?\n/.test(text);                    // đủ dùng cho hầu hết trường hợp
      }
    async onBarcodeScanned(barcode) {
        if (barcode) {

            if(this.containsLineBreak(barcode))
            {
                const normalized = barcode.replace(/\r\n|[;,]/g, '\n'); // đổi toàn bộ CRLF thành LF
                const lines2 = normalized.split('\n'); 
                for (var line of lines2){
                    await this.processBarcode(line, this.picking_id)
                }
            }
            else{
                await this.processBarcode(barcode, this.picking_id)
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
    async processBarcode(barcode, picking_id) {
        if (this.state.isSelector) {
            if (this.state.view == "Move") {
                var barcodeData = await this.env.model.parseBarcode(barcode, false, false, false)
                //console.log(barcodeData)
                if (barcodeData.match) {
                    if (barcodeData.barcodeType == "products") {
                        if (barcodeData.fromCache) {
                            var move = this.env.model.data.moves.find(x => x.product_id == barcodeData.record.id)
                            this.state.selectedMove = move.id
                        }
                        else {
                            var product_id = barcodeData.record.id
                            var name = barcodeData.record.display_name
                            var location_id = this.env.model.data.location_id
                            var location_dest_id = this.env.model.data.location_dest_id
                            var values = { picking_id, product_id, name, location_id, location_dest_id }
                            var data = await this.orm.call('stock.picking', 'create_move', [, picking_id, values], {});
                            this.env.model.data = data.data
                            this.state.moves = this.env.model.data.moves.sort((a, b) => b.product_name.localeCompare(a.product_name));
                            this.state.selectedMove = data.move_id
                            console.log(data)
                        }
                    }
                    if (barcodeData.barcodeType == "packages") {
                        if (barcodeData.fromCache) {
                            for (var product of barcodeData.record.products) {
                               var move = this.env.model.data.moves.find(x => x.product_id == product.product_id)
                               this.state.selectedMove = move.id
                            }
                        }
                        else {
                            if ((this.env.model.data.state != 'done' && this.env.model.data.state != 'cancel')) {
                                if (this.env.model.data.picking_type_code != "incoming") {
                                    // if(await this.orm.call('stock.picking', 'check_package_location', [,barcodeData.record.id,this.env.model.data.location_id],{})) 
                                    // {
                                        var values = {}
                                        for (var product of barcodeData.record.products) {
                                            
                                            values.product_id = product.product_id
                                            values.product_uom_id = product.product_uom_id
                                            values.location_id = product.location_id
                                            values.location_dest_id = this.env.model.data.location_dest_id
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
                                            this.env.model.data = data
                                            this.state.moves = this.env.model.data.moves.sort((a, b) => b.product_name.localeCompare(a.product_name));
                                        }
                                    // }
                                    // else{
                                    //     const message = _t(`${barcode}: Không đang ở vị trí ${this.env.model.data.location_name} !`);
                                    //     this.notification.add(message, { type: "warning" });
                                    // }
                                    
                                }
                                else{
                                    var line_incoming = this.env.model.data.move_lines.find(x=>x.result_package_id == barcodeData.record.id)
                                    var move_incoming = this.state.moves.find(x=>x.id == line_incoming.move_id) 
                                    if(move_incoming){
                                        this.editMove(move_incoming.id)
                                    }
                                    else{
                                        const message = _t(`Gói đích này: ${barcode} không có trong danh sách!`);
                                        this.notification.add(message, { type: "warning" });
                                    }
                                }
                            }
                            else{
                                const message = _t(`Đơn đã hoàn tất, không thể thêm sản phẩm vào đơn !`);
                                this.notification.add(message, { type: "warning" });
                            }
                        }
                    }
                    if(barcodeData.barcodeType == "lots"){
                       
                        if ((this.env.model.data.state != 'done' && this.env.model.data.state != 'cancel')) {
                            if (this.env.model.data.picking_type_code != "incoming") {
                                let quants = await this.orm.searchRead('stock.quant', [['lot_id','=',barcodeData.record.id],['location_id.usage','=','internal']], ['id', 'available_quantity','package_id','location_id','product_id','product_uom_id']);
                                if (quants){
                                    for (var quant of quants){
                                        if(quant.available_quantity >0){
                                            var values = {}                                      
                                            values.product_id = quant.product_id[0]
                                            values.product_uom_id = quant.product_uom_id[0]
                                            values.location_id =  quant.location_id[0]
                                            values.location_dest_id = this.env.model.data.location_dest_id
                                            values.lot_id = barcodeData.record.id
                                            values.lot_name = barcode
                                            values.package_id = quant.package_id[0]
                                       
                                            values.quantity = quant.available_quantity
                                            values.picked = true
                                            values.picking_id = this.picking_id
                                            values.id = false
                                            values.move_id = false
                                            var data = await this.orm.call('stock.picking', 'save_data', [, picking_id, values,this.batch_id], {});
                                            this.env.model.data = data
                                            this.state.moves = this.env.model.data.moves.sort((a, b) => b.product_name.localeCompare(a.product_name));
                                        }
                                        
                                    }
                                    
                                }
                               
                                else{
                                    const message = _t(`${barcode}: Không có sẵn ở trong kho !`);
                                    this.notification.add(message, { type: "warning" });
                                }
                                
                            }
                            else{                           
                                    const message = _t(`Số lô/sê-ri ${barcode} đã có trong hệ thống!`);
                                    this.notification.add(message, { type: "warning" });
                            }
                        }
                        else{
                            const message = _t(`Đơn đã hoàn tất, không thể thêm sản phẩm vào đơn !`);
                            this.notification.add(message, { type: "warning" });
                        }

                    }
                }
                else {
                    const message = _t(`Không có thấy thông tin của barcode: ${barcode}!`);
                    this.notification.add(message, { type: "warning" });
                }
            }
            if (this.state.view == "Move_line") {
                var barcodeData = await this.env.model.parseBarcode(barcode, {'product_id':this.state.detailMoveLine.product_id}, false, false)
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
                                    this.env.model.data = data
                                    this.editMove(this.state.detailMoveLine.move_id)
                                    this.state.scannedLine = false
                                }
                                else{
                                    const message = _t(`Gói đích này: ${barcode} không đúng!`);
                                    this.notification.add(message, { type: "warning" });
                                }
                                
                            }
                            else{
                                if (this.env.model.data.picking_type_code != "incoming") {
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
                                                        console.log({prod,lots:this.props.lots})
                                                        var lot = this.env.model.data.lots.find(x=> x.expiration_date <  prod.expiration_date)
                                                        if(lot){
                                                            const message = _t(`Số lô: ${prod.lot_name} có ngày hết hạn lớn hơn ngày hết hạn của lô: ${lot.name}!`);
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
                                                                this.env.model.data = data
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
                                                            this.env.model.data = data
                                                            this.editMove(this.state.detailMoveLine.move_id)
                                                        }
                                                    }
                                                }
                                                else
                                                {
                                                    console.log({prod,lots:this.env.model.data.lots})
                                                        var lot = this.env.model.data.lots.find(x=> x.expiration_date <  prod.expiration_date)
                                                        if(lot){
                                                            const message = _t(`Số lô: ${prod.lot_name} có ngày hết hạn lớn hơn ngày hết hạn của lô: ${lot.name}!`);
                                                            this.notification.add(message, { type: "warning" });
                                                        }
                                                    var line = this.lines.find(x=>x.package_id == barcodeData.record.id && x.lot_id == prod.lot_id)
                                                    console.log({line,lines:this.lines,record:barcodeData.record})
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
                                                            this.env.model.data = data
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
                                                                    this.env.model.data = data
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
                                                                this.env.model.data = data
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
                                                            this.env.model.data = data
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
                                                    const message = _t(`Package: "${barcode}" không còn đủ số lượng khả dụng`);
                                                    this.notification.add(message, { type: "warning" });
                                                }
                                            }
            
                                            
                                            
                                            
                                        }
                                    }
                                    else
                                    {
                                        const message = _t(`Package: "${barcode}" không nằm ở vị trí: "${this.state.detailMoveLine.location_name}". Nó đang nằm ở vị trí: "${barcodeData.record.location_name}"`);
                                        this.notification.add(message, { type: "warning" });
                                    }
                                    
                                }
                                else
                                {
                                    var incoming_line = this.state.lines.find(x=>x.result_package_id == barcodeData.record.id)
                                    if(incoming_line){
                                        var data = await this.orm.call('stock.picking', 'save_data', [, this.picking_id, incoming_line,this.batch_id], {});
                                        this.env.model.data = data
                                        this.editMove(this.state.detailMoveLine.move_id)
                                        
                                    }
                                    else{
                                        const message = _t(`Gói đích này: ${barcode} không có trong danh sách!`);
                                        this.notification.add(message, { type: "warning" });
                                    }
                                }
                            }
                            
                        }
                        else if(barcodeData.barcodeType == "lots" && barcodeData.record.product_id[0] == this.state.detailMoveLine.product_id){
                            if(this.state.detailMoveLine.product_tracking == "lot"){
                                this.state.detailMoveLine.lot_name = barcodeData.barcode
                                this.state.detailMoveLine.lot_id = barcodeData.record.id
                                this.state.detailMoveLine.quantity += 1
                            }
                            else if(this.state.detailMoveLine.product_tracking == "serial"){
                                let line_serial = this.state.lines.find(x=>x.lot_name == barcode)
                                if(line_serial){
                                    var data = await this.orm.call('stock.picking', 'save_data', [, this.picking_id, line_serial,this.batch_id], {});
                                    this.env.model.data = data
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
    
                        }
                        else if(barcodeData.barcodeType == "locations"){
                            if(this.state.detailMoveLine.picking_type_code == 'incoming')
                            {
                                this.state.detailMoveLine.location_dest_id = barcodeData.record.id
                                this.state.detailMoveLine.location_dest_name = barcodeData.record.display_name
                            }
                            else if(this.state.detailMoveLine.picking_type_code == 'outgoing')
                            {
                                this.state.detailMoveLine.location_id = barcodeData.record.id
                                this.state.detailMoveLine.location_name = barcodeData.record.display_name
                            }
                            else
                            {
                                if(this.move.location_id == this.state.detailMoveLine.location_id)
                                {
                                    this.state.detailMoveLine.location_id = barcodeData.record.id
                                    this.state.detailMoveLine.location_name = barcodeData.record.display_name
                                }
                                else
                                {
                                    this.state.detailMoveLine.location_dest_id = barcodeData.record.id
                                    this.state.detailMoveLine.location_dest_name = barcodeData.record.display_name
                                }
                            }
    
                        }
                    }
                    else{
                        if(this.state.detailMoveLine.picking_type_code == 'incoming'){
                            let line_serial = this.state.lines.find(x=>x.lot_name == barcode)
                            if(line_serial){
                                var data = await this.orm.call('stock.picking', 'save_data', [, this.picking_id, line_serial,this.batch_id], {});
                                this.env.model.data = data
                                this.editMove(this.state.detailMoveLine.move_id)
                            }
                            else{ 
                                this.state.detailMoveLine.quantity = 1                              
                                this.state.detailMoveLine.lot_name =barcode          
                                this.save() 
                            }
                        }
                        
                        else{ 
                            const message = _t(`Không tìm thấy barcode: "${barcode}" trong hệ thống!`);
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
                        const message = _t(`Barcode: ${barcode} có giá trị không phải là số!`);
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
                        const message = _t(`Barcode: ${barcode} là ${barcodeData.barcodeType} nên không dùng được!`);
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
                        const message = _t(`Barcode: ${barcode} là ${barcodeData.barcodeType} nên không dùng được!`);
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
                        const message = _t(`Barcode: ${barcode} là ${barcodeData.barcodeType} nên không dùng được!`);
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
                            const message = _t(`Vui lòng cập nhật các thông số lệnh trước khi đóng pack!`);
                            this.notification.add(message, { type: "warning" });
                        }
                        
                    }
                    else
                    {
                        const message = _t(`Barcode: ${barcode} là ${barcodeData.barcodeType} nên không dùng được!`);
                        this.notification.add(message, { type: "warning" });
                    }
                }
                
            }
            this.updateButton()
        }
    }

}


StockPicking.props = ["action?", "actionId?", "className?", "globalState?", "resId?"];
StockPicking.template = 'smartbiz_barcode.StockPicking';
StockPicking.components = {
    KeyPad, Selector, ManualBarcodeScanner
};

registry.category("actions").add("smartbiz_barcode_picking_action", StockPicking);

export default StockPicking;
