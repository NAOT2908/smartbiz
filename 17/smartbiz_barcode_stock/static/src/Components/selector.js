/** @odoo-module **/
import { Component, useState, xml } from '@odoo/owl';
import { registry } from "@web/core/registry";
import { useService,useBus } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { ManualBarcodeScanner } from "@smartbiz_barcode/Components/manual_barcode";
import * as BarcodeScanner from "@web/webclient/barcode/barcode_scanner";
export class Selector extends Component {
    static props = ['records', 'multiSelect?', 'closeSelector', 'title','function','move?','isSelector?','lots?'];
    static template = "smartbiz_barcode_stock.Selector"
    setup() {
        this._t = _t;
        this.dialogService = useService("dialog");
        this.actionManager = useService("action");
        this.notification = useService("notification");
        this.dialog = useService("dialog");
        this.orm = useService("orm");
        this.rpc = useService("rpc");
        this.state = useState({
            searchQuery: "",
            selectedRecords: [],
            quantity: false,
            showCreateNew: false,
            selectedRecord: 0,
            package:{},
            packageId:0,
            packageName:'',
            packageProductQty:'',
            qtyPerPackage:'',
            packageQty:'',
            showPackageQty: true,  // Điều khiển hiển thị 'Số lượng Package mới'
            processedPackages: [],  // Danh sách các package đã xử lý
            processedSerials: [],  // Danh sách các serial đã xử lý

            lot_name: this.props.move.lot_name || ''

        });
        this.barcodeService = useService("barcode");
        useBus(this.barcodeService.bus, "barcode_scanned", (ev) =>

            this.onBarcodeScanned(ev.detail.barcode)
          );
        if (this.props.title === "Select Lot/Serial" || this.props.title === "Select Destination Package") {
            this.state.showCreateNew = true;
        }
    }
    willUpdateProps(nextProps) {
       this.state.barcodeData = nextProps.barcodeData
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

    /* Xoá một package theo id */
    removeProcessedPackage(pkgId) {
        const idx = this.state.processedPackages.findIndex(p => p.id === pkgId);
        if (idx > -1) {
            this.state.processedPackages.splice(idx, 1);
        }
    }

    /* Xoá một serial (serial là chuỗi) */
    removeProcessedSerial(serial) {
        const idx = this.state.processedSerials.findIndex(s => s === serial);
        if (idx > -1) {
            this.state.processedSerials.splice(idx, 1);
        }
    }

    async processBarcode(barcode){
        var barcodeData = await this.orm.call('stock.picking', 'get_barcode_data', [,barcode,false,false],{});
        //console.log(barcodeData)
        if (barcodeData.match) {
            
            if (barcodeData.barcodeType == "packages") {
                if(!this.state.packageId){
                    this.state.package = barcodeData.record
                    this.state.packageProductQty = 0;
                    for (var prod of barcodeData.record.products.filter((x) => x.product_id == this.props.move.product_id )) {
                        this.state.packageProductQty += prod.available_quantity
                        
                    }
                    this.state.packageName = barcodeData.barcode
                    this.state.packageId = barcodeData.record.id
                    
                }
                else if(this.state.packageId != barcodeData.record.id && !this.state.showPackageQty){
                    this.state.processedPackages.push({
                        id: barcodeData.record.id,
                        name: barcodeData.barcode
                    });
                }
                
            }
            else if (barcodeData.barcodeType == "lots") {
                if (this.props.title === "Receive by Serial") {    
                    if(this.props.records.find(x=>x.lot_name == barcode)){
                        const message = _t(`The ${barcode} is already in stock!`);
                        this.notification.add(message, { type: "warning" });
                        return;
                    }
                    if(await this.orm.call('stock.picking', 'check_serial_number', [,barcodeData.record.id], {})){
                        const message = _t(`The ${barcode} is already in stock!`);
                        this.notification.add(message, { type: "warning" });
                    }
                    else{
                        if(!this.state.processedSerials.find(x=>x == barcode)){
                            this.state.processedSerials.push(barcode)                                      
                        }
                        else{
                            const message = _t(`The ${barcode} has been scanned!`);
                            this.notification.add(message, { type: "warning" });
                        }
                    }
                    
                }
            }
            else{            
                const message = _t(`Barcode: ${barcode} is not a Package!`);
                this.notification.add(message, { type: "warning" });
            }
        } else {
            if (this.props.title === "Receive by Serial"){
                if(this.props.records.find(x=>x.lot_name == barcode)){
                    const message = _t(`The ${barcode} is already in stock!`);
                    this.notification.add(message, { type: "warning" });
                    return;
                }
                if(!this.state.processedSerials.find(x=>x == barcode)){
                    this.state.processedSerials.push(barcode)                                      
                }
                else{
                    const message = _t(`The ${barcode} has been scanned!`);
                    this.notification.add(message, { type: "warning" });
                }
            }
            else{
                const message = _t(`No barcode information found: ${barcode}!`);
                this.notification.add(message, { type: "warning" });
            }

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
    get filteredRecords() {
        const searchLower = this.state.searchQuery.toLowerCase();
        return this.props.records.filter(record =>
            (record.display_name ? record.display_name.toLowerCase() : record.name.toLowerCase()).includes(searchLower)
        );
    }

    selectRecord(recordId) {
        const index = this.state.selectedRecords.indexOf(recordId);
        if (this.props.multiSelect) {
            if (index > -1) {
                this.state.selectedRecords.splice(index, 1); // Remove if already selected
            } else {
                this.state.selectedRecords.push(recordId); // Add to selection
            }
        } else {
            if (this.props.title === "Select Product") {
                const record = this.props.records.find(x => x.id === recordId);
                const data = {
                    product_id: recordId,
                    quantity: this.state.quantity,
                    display_name: record.display_name,
                };
                this.props.closeSelector(data);
            } else {
                if(this.state.selectedRecord == recordId)
                    this.state.selectedRecord = 0
                else
                    this.state.selectedRecord = recordId
            }
        }
    }

    async confirmSelection() {
        if(this.props.isSelector){
            if(this.state.selectedRecord){
                //console.log(this.state.selectedRecords)
                this.props.closeSelector(this.props.records.find(x=>x.id == this.state.selectedRecord));
            }    
            else{
                //console.log(this.state.selectedRecords)
                this.props.closeSelector(Object.values(this.state.selectedRecords));
            }
        }
        else{
            if(this.props.title == "Split Packages"){
                var lines =  await this.createLinesFromInventory(
                    this.state.package.products.filter((x) => x.product_id == this.props.move.product_id ),
                    this.state.qtyPerPackage, 
                    this.state.packageQty, 
                    this.props.move, 
                    this.state.package, 
                    this.state.showPackageQty, 
                    this.state.processedPackages
                )
                console.log(lines)
                this.props.closeSelector(lines);
            }
            else if (this.props.title == 'Bulk Pack') {
                let qtyPerPackage = parseFloat(this.state.qtyPerPackage);
                let packageQty = parseInt(this.state.packageQty);

                if (isNaN(qtyPerPackage) || isNaN(packageQty) || qtyPerPackage <= 0 || packageQty <= 0) {
                    this.notification.add(_t("Please enter a valid quantity for quantity per pack and number of packs."), { type: "warning" });
                    return;
                }

                let lotName = this.state.lot_name.trim();
                if (this.props.move.product_tracking !== 'none') {
                    if (!lotName) {
                        this.notification.add(_t("Please enter batch number."), { type: "warning" });
                        return;
                    }
                } else {
                    lotName = '';
                }

                var lines = await this.createLinesFromDemandQty(
                    this.props.move,
                    qtyPerPackage,
                    packageQty,
                    lotName
                );
                this.props.closeSelector(lines);
            }
            else if (this.props.title == "Receive by Serial") {
                let qtyPerPackage = parseFloat(this.state.qtyPerPackage);
               

               

                var lines = await this.createLinesWithSerials(
                    this.props.move,
                    qtyPerPackage,
                    this.state.processedSerials,
                    this.state.processedPackages
                );
                this.props.closeSelector(lines);
            }
        
            
            
        }
           
        
    }

    cancelSelection() {
        this.props.closeSelector(false);
    }
    async editRecord(id){
        if (this.props.title === "Select Destination Package") {
            const action = {
                type: 'ir.actions.act_window',
                res_model: 'stock.quant.package',
                res_id:id,
                views: [[false, 'form']],
                target: 'new',
            };
        
           await this.actionManager.doAction(action, {
                onClose: async () => {               
                    this.props.closeSelector(this.props.records.find(x=>x.id == this.state.selectedRecord));
                },
            });
            
        }
        else{
            this.props.closeSelector(this.props.records.find(x=>x.id == this.state.selectedRecord));
        }
    }
    async createNew() {
        if (this.props.title === "Select Destination Package") {
            const action = {
                type: 'ir.actions.act_window',
                res_model: 'stock.quant.package',
                views: [[false, 'form']],
                target: 'new',
            };
        
           await this.actionManager.doAction(action, {
                onClose: async (x) => {
                        
                        const newRecord = await this.orm.searchRead('stock.quant.package', [], ['id', 'name'],{
                            order: "create_date desc",
                            limit: 1
                        });
                        console.log(newRecord[0])
                        this.props.closeSelector(newRecord[0]);

                    
                },
            });
            
        }
        else if(this.props.title === "Select Lot/Serial")
        {
            const action = {
                type: 'ir.actions.act_window',
                res_model: 'stock.lot',
                views: [[false, 'form']],
                context:{'default_product_id':this.props.move.product_id},
                target: 'new',
            };
        
           await this.actionManager.doAction(action, {
                onClose: async (x) => {
                        
                        const newRecord = await this.orm.searchRead('stock.lot', [], ['id', 'name'],{
                            order: "create_date desc",
                            limit: 1
                        });
                        console.log(newRecord[0])
                        this.props.closeSelector(newRecord[0]);

                    
                },
            });
            
        }
        else{
            this.props.closeSelector(false);
        }
        
    }

    //Hàm để tạo move line từ package được quét vào
    async createLinesFromInventory(inventoryList, qtyPerPackage, packageQty, move, srcPackage, showPackageQty, processedPackages) {
        const lines = [];
        let currentPackageQty = 0; // Đếm số lượng package đã tạo
        let remainingQtyPerPackage = qtyPerPackage; // Số lượng còn lại để lấp đầy 1 package
        let resultPackageId = null; // Giữ lại resultPackageId để tiếp tục sử dụng nếu cần
        let resultPackageName = ''; // Giữ lại resultPackageId để tiếp tục sử dụng nếu cần
        // Nếu showPackageQty là false, thì số lượng packageQty sẽ là số phần tử của processedPackages
        if (!showPackageQty) {
            packageQty = processedPackages.length;
        }
    
        // Vòng lặp qua danh sách tồn kho và tạo các line
        for (let inventory of inventoryList) {
            let availableQty = inventory.available_quantity;
    
            while (availableQty > 0 && currentPackageQty < packageQty) {
                // Tính số lượng cần thêm vào line hiện tại
                let quantityToTake = Math.min(availableQty, remainingQtyPerPackage);
    
                // Nếu showPackageQty = true, tạo package mới khi thùng đầy
                if (showPackageQty && remainingQtyPerPackage === qtyPerPackage) {
                    // Tạo package mới nếu chưa có hoặc thùng trước đã đầy
                    let packageName = '';
                    let data = await this.orm.call(
                        "stock.picking",
                        "create_package",
                        [null, packageName],
                        {}
                    );
                    resultPackageId = data.id; // Gán id của package mới
                    resultPackageName = data.name
                } else if (!showPackageQty) {
                    // Nếu showPackageQty = false, sử dụng processedPackages
                    let currentPackage = processedPackages[currentPackageQty];
                    if (currentPackage.id) {
                        resultPackageId = currentPackage.id; // Sử dụng id đã có
                        resultPackageName = currentPackage.name
                    } else {
                        // Tạo package mới nếu không có id trong processedPackages
                        let packageName = currentPackage.name || '';
                        let data = await this.orm.call(
                            "stock.picking",
                            "create_package",
                            [null, packageName],
                            {}
                        );
                        resultPackageId = data.id;
                        resultPackageName = data.name
                    }
                }
    
                // Tạo line với thông tin từ move và inventory
                let line = {
                    id: 0,
                    move_id: move.id,
                    product_id: move.product_id,
                    product_name: move.product_name,
                    location_name: inventory.location_name,
                    location_id: inventory.location_id,
                    location_dest_name: move.location_dest_name,
                    location_dest_id: move.location_dest_id,
                    lot_id: inventory.lot_id,
                    lot_name: '', // Tên Lot (nếu có)
                    product_uom_id: move.product_uom_id,
                    package_id: srcPackage ? srcPackage.id : null, // Gán srcPackage vào package_id
                    package_name: srcPackage ? srcPackage.name : null,
                    result_package_id: resultPackageId, // Gán cuộn đích vào result_package_id
                    result_package_name: resultPackageName, // Tên cuộn đích
                    product_uom_qty: move.product_uom_qty,
                    quantity: 0,
                    quantity_done: move.quantity,
                    quantity_need: this.roundToTwo(move.product_uom_qty - move.quantity),
                    product_uom: move.product_uom,
                    product_tracking: move.product_tracking,
                    picking_type_code: move.picking_type_code,
                    state: "draft",
                    package: true,
                    picking_id: move.picking_id,
                };
    
                // Gán quantity cho line
                line.quantity = quantityToTake;
    
                // Trừ bớt số lượng đã sử dụng khỏi availableQty và remainingQtyPerPackage
                availableQty -= quantityToTake;
                remainingQtyPerPackage -= quantityToTake;
    
                // Nếu đã lấp đầy một package
                if (remainingQtyPerPackage === 0) {
                    currentPackageQty++; // Tăng số lượng package đã tạo
                    remainingQtyPerPackage = qtyPerPackage; // Reset lại cho package tiếp theo
                }
    
                // Thêm line vào danh sách
                lines.push(line);
    
                // Kiểm tra nếu đã đạt đủ packageQty
                if (currentPackageQty >= packageQty) {
                    break;
                }
            }
    
            // Nếu đã đủ số lượng package thì dừng vòng lặp
            if (currentPackageQty >= packageQty) {
                break;
            }
        }
    
        return lines;
    }
    
    //Hàm để tạo move line nhập bằng cách khai báo theo số lượng nhập
    async createLinesFromDemandQty(move, qtyPerPackage, packageQty, lotName) {
        const lines = [];
        let remainingQty = this.roundToTwo(move.product_uom_qty - move.quantity);

        for (let i = 0; i < packageQty && remainingQty > 0; i++) {
            let data = await this.orm.call(
                "stock.picking",
                "create_package",
                [null, ''],
                {}
            );
            let resultPackageId = data.id;
            let resultPackageName = data.name;

            let quantityToAssign = this.roundToTwo(Math.min(qtyPerPackage, remainingQty));

            let line = {
                id: 0,
                move_id: move.id,
                product_id: move.product_id,
                product_name: move.product_name,
                location_id: move.location_id,
                location_name: move.location_name,
                location_dest_id: move.location_dest_id,
                location_dest_name: move.location_dest_name,
                lot_name: lotName, // Use lot_name if provided
                lot_id:null,
                product_uom_id: move.product_uom_id,
                package_id: null,
                package_name: null,
                result_package_id: resultPackageId,
                result_package_name: resultPackageName,
                product_uom_qty: move.product_uom_qty,
                quantity: quantityToAssign,
                quantity_done: quantityToAssign,
                quantity_need: this.roundToTwo(move.product_uom_qty - move.quantity - quantityToAssign),
                product_uom: move.product_uom,
                product_tracking: move.product_tracking,
                picking_type_code: move.picking_type_code,
                state: "draft",
                package: true,
                picking_id: move.picking_id,
            };

            lines.push(line);

            remainingQty -= quantityToAssign;
        }

        return lines;
    }
    // Tạo move‑line theo từng serial và gán package (ưu tiên line trống sẵn có)
    async createLinesWithSerials(move, qtyPerPackage, processedSerials = [], processedPackages = []) {
        const lines = [];                                // kết quả trả về

        /* ------------------------------------------------------------------
        1. Tính số serial đã gán & các line trống
        ------------------------------------------------------------------ */
        const allMoveLines = (this.props.records || []).filter(l => l.move_id === move.id);

        // 1.1 Các line đã có serial (lot_id / lot_name) ⇒ đã “dùng” số lượng
        const assignedQty = allMoveLines
            .filter(l => l.lot_id || l.lot_name)
            .reduce((acc, l) => acc + (l.quantity_done || l.quantity || 1), 0);

        // 1.2 Các line trống serial (ưu tiên gán serial mới vào đây)
        const blankLines = allMoveLines.filter(l => !l.lot_id && !l.lot_name);
        let blankIdx = 0;   // con trỏ line trống kế tiếp

        // 1.3 Xác định remainingQty theo yêu cầu mới
        let remainingQty = this.roundToTwo(move.product_uom_qty - assignedQty);
        if (!processedSerials.length || remainingQty <= 0) {
            return lines;    // Không cần tạo thêm
        }

        /* ------------------------------------------------------------------
        2. Tiện ích package
        ------------------------------------------------------------------ */
        let pkgIdx = 0;       // vị trí trong processedPackages
        let pkgFill = 0;      // serial đã “nạp” vào package hiện tại
        let currentPkg = { id: null, name: null };

        const nextPackage = async () => {
            if (!qtyPerPackage || qtyPerPackage <= 0) return { id: null, name: null };
            if (pkgIdx < processedPackages.length) {
                const p = processedPackages[pkgIdx];
                pkgIdx += 1;
                return { id: p.id || null, name: p.name || null };
            }
            const p = await this.orm.call("stock.picking", "create_package", [null, ""], {});
            return { id: p.id, name: p.name };
        };

        /* ------------------------------------------------------------------
        3. Gán từng serial
        ------------------------------------------------------------------ */
        let serialCount = assignedQty;   // tổng serial đã gán (cũ + mới)

        for (const serial of processedSerials) {
            if (remainingQty <= 0) break;

            // 3.1 Package: đổi khi đầy
            if (qtyPerPackage && qtyPerPackage > 0) {
                if (!currentPkg.id || pkgFill >= qtyPerPackage) {
                    currentPkg = await nextPackage();
                    pkgFill = 0;
                }
                pkgFill += 1;
            }

            /* 3.2 Chọn line đích */
            let targetLine;
            if (blankIdx < blankLines.length) {
                targetLine = blankLines[blankIdx];
                blankIdx += 1;

                // cập nhật serial & package
                targetLine.lot_id              = serial.id || null;
                targetLine.lot_name            = serial.name || serial;
                targetLine.result_package_id   = currentPkg.id;
                targetLine.result_package_name = currentPkg.name;
                targetLine.quantity            = 1;
                targetLine.quantity_done       = 1;
                // quantity_need = còn lại sau khi đã gán serialCount+1
                targetLine.quantity_need       = this.roundToTwo(move.product_uom_qty - (serialCount + 1));
                targetLine.state               = "draft";

                lines.push(targetLine);
            } else {
                /* Không còn line trống → tạo mới */
                const line = {
                    id: 0,
                    move_id:            move.id,
                    product_id:         move.product_id,
                    product_name:       move.product_name,
                    location_id:        move.location_id,
                    location_name:      move.location_name,
                    location_dest_id:   move.location_dest_id,
                    location_dest_name: move.location_dest_name,
                    lot_id:             serial.id || null,
                    lot_name:           serial.name || serial,
                    product_uom_id:     move.product_uom_id,
                    package_id:         null,
                    package_name:       null,
                    result_package_id:   currentPkg.id,
                    result_package_name: currentPkg.name,
                    product_uom_qty:    move.product_uom_qty,
                    quantity:           1,
                    quantity_done:      1,
                    quantity_need:      this.roundToTwo(move.product_uom_qty - (serialCount + 1)),
                    product_uom:        move.product_uom,
                    product_tracking:   move.product_tracking,
                    picking_type_code:  move.picking_type_code,
                    state:              "draft",
                    package:            true,
                    picking_id:         move.picking_id,
                };
                lines.push(line);
            }

            serialCount += 1;
            remainingQty -= 1;
        }

        return lines;
    }

    roundToTwo(num) {
        return Math.round(num * 100) / 100;
    }
    
    
}


