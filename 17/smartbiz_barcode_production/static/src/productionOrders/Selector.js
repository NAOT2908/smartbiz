/** @odoo-module **/
import { Component,
    EventBus,
    onPatched,
    onWillStart,
    useState,
    useSubEnv,
    xml, } from '@odoo/owl';
import { _t } from "@web/core/l10n/translation";
import { ManualBarcodeScanner } from "@smartbiz_barcode/Components/manual_barcode";
import * as BarcodeScanner from "@web/webclient/barcode/barcode_scanner";
import { useService,useBus } from "@web/core/utils/hooks";
import SmartBizBarcodePickingModel from "@smartbiz_barcode/Models/barcode_picking";
import { utils as uiUtils } from "@web/core/ui/ui_service";

export class Selector extends Component {
    setup() {
        this.rpc = useService('rpc');
        this.orm = useService('orm');
        this.notification = useService('notification');
        this.dialog = useService('dialog');
        this.action = useService('action');
        this.home = useService("home_menu");

        this.state = useState({
            searchQuery: "",
            selectedRecords: [],
            quantity:false,
            records: this.props.records,
            selectedRecord: 0,
            package:{},
            packageId:0,
            packageName:'',
            packageProductQty:'',
            qtyPerPackage:'',
            remainingQty: this.roundToTwo(this.props.move.product_uom_qty - this.props.move.quantity),
            packageQty:'',
            lot_name: this.props.records.lot_name,
            lot_id: this.props.records.lot_id,
            createPackageQty: false,
            showPackageQty: true,  // Điều khiển hiển thị 'Số lượng Package mới'
            processedPackages: [],  // Danh sách các package đã xử lý
            resultPackages: [],  // Danh sách các package qu
            
        });
        // for (var r of this.state.records){
        //     r.quantity_remain = 0
        // }

        console.log(this.props.isSelector, this.props.records, this.props.move)
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
    }

    get filteredRecords() {
        const searchLower = this.state.searchQuery.toLowerCase();
        return this.state.records.filter(record => 
            (record.display_name ? record.display_name.toLowerCase() : record.name? record.name.toLowerCase():record.product_name.toLowerCase()).includes(searchLower)
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
            if(this.props.title == "Chọn sản phẩm")
            {
                var record = this.props.records.find(x=>x.id ==recordId)
                var data = {
                    product_id: recordId,
                    quantity: this.state.quantity,
                    display_name:record.display_name,
                }
                this.props.closeSelector(data);
            }
            else{
                if(this.state.selectedRecord == recordId)
                    this.state.selectedRecord = 0
                else
                    this.state.selectedRecord = recordId
            }
            
        }
    }

    roundToTwo(num) {
        return Math.round(num * 100) / 100;
    }
    
    async createLinesFromDemandQty(move, qtyPerPackage, packageQty, lotName) {
        const lines = [];
        console.log(move)
        let remainingQty = this.state.remainingQty;
        const Qtypackage = this.state.createPackageQty ? packageQty : this.state.resultPackages.length;
        
        if (packageQty <= 0 || remainingQty <= 0) {
            console.warn("Số lượng package hoặc số lượng cần cấp phát không hợp lệ!");
            return [];
        }
    
        if (!this.state.createPackageQty && (!this.state.resultPackages || this.state.resultPackages.length < packageQty)) {
            this.notification.add(_t("Không đủ Package đích để sử dụng!"), { type: "warning" });
            return [];
        }
    
        for (let i = 0; i < Qtypackage && remainingQty > 0; i++) {
            let resultPackageId, resultPackageName;
    
            if (this.state.createPackageQty) {
                let data = await this.orm.call("mrp.production", "create_package", [null, ''], {});
                console.log("Tạo package mới:", data);
                if (!data || !data.id) {
                    console.error("Lỗi khi tạo package!");
                    return [];
                }
                resultPackageId = data.id;
                resultPackageName = data.name;
            } else {
                if (this.state.resultPackages.length > i) {
                    resultPackageId = this.state.resultPackages[i].id;
                    resultPackageName = this.state.resultPackages[i].name;
                } else {
                    console.warn(`Không đủ Package đích để sử dụng! Đang tạo mới với tên đã quét.`);
                    let packageName = this.state.scannedPackageName || "Package_Mặc_Định";
                    let data = await this.orm.call("mrp.production", "create_package", [null, packageName], {});
                    resultPackageId = data.id;
                    resultPackageName = data.name;
                    this.state.resultPackages.push({ id: data.id, name: data.name });
                    }
            }
    
            let quantityToAssign = this.roundToTwo(Math.min(qtyPerPackage, remainingQty));
            console.log("Số lượng cần cấp phát:", quantityToAssign);
    
            if (quantityToAssign <= 0) {
                console.warn("Không có số lượng hợp lệ để cấp phát!");
                break;
            }
    
            let line = {
                id: 0,
                move_id: move.id,
                product_id: move.product_id,
                product_name: move.product_name,
                location_id: move.location_id,
                location_name: move.location_name,
                location_dest_id: move.location_dest_id,
                location_dest_name: move.location_dest_name,
                lot_name: lotName,
                lot_id: null,
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
    
        console.log("Danh sách lines sau khi tạo:", lines);
        return lines;
    }
    
    

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
                        "mrp.production",
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
                            "mrp.production",
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

    async confirmSelection() {
        if(this.props.isSelector){
            if(this.props.title == "Nguyên liệu còn lại"){
                this.props.closeSelector(this.state.records,'Nguyên liệu còn lại');
            }
            else if(this.props.title == "Chọn vị trí nguồn"){
                this.props.closeSelector(this.state.records.find(x=>x.id == this.state.selectedRecord),'Chọn vị trí nguồn');
            }
            else if(this.props.title == "Chọn vị trí đích"){
                this.props.closeSelector(this.state.records.find(x=>x.id == this.state.selectedRecord),'Chọn vị trí đích');
            }
            else if(this.props.title == "Chọn số Lô/Sê-ri"){
                this.props.closeSelector(this.state.records.find(x=>x.id == this.state.selectedRecord),'Chọn số Lô/Sê-ri');
            }
            else if(this.props.title == "Chọn kiện đích"){
                this.props.closeSelector(this.state.records.find(x=>x.id == this.state.selectedRecord),'Chọn kiện đích');
            }
            else if(this.props.title == "Chọn kiện nguồn"){
                this.props.closeSelector(this.state.records.find(x=>x.id == this.state.selectedRecord),'Chọn kiện nguồn');
            }
            else
            {
                this.props.closeSelector(this.state.selectedRecords);
            } 
        } else {
            if(this.props.title == 'Chia tách Packages'){
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
            else if (this.props.title == 'Đóng Packages loạt') {
                console.log(this.props.move)
                let qtyPerPackage = parseFloat(this.state.qtyPerPackage);
                let packageQty = parseInt(this.state.packageQty);
                
                if(this.state.createPackageQty){
                    if (isNaN(qtyPerPackage) || isNaN(packageQty) || qtyPerPackage <= 0 || packageQty <= 0) {
                        this.notification.add(_t("Vui lòng nhập số lượng hợp lệ cho số lượng trên một pack và số pack."), { type: "warning" });
                        return;
                    }
                }
                
                let lotName = this.state.lot_name ? this.state.lot_name.trim() : "";
                if (this.props.move.product_tracking !== 'none') {
                    if (!lotName) {
                        this.notification.add(_t("Vui lòng nhập số lô."), { type: "warning" });
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
                console.log(lines, lotName)
                this.props.closeSelector(lines);
            }
        }
    }

    cancelSelection() {
        this.props.closeSelector(false);
    }
    createNew() {
        this.props.closeSelector(this.state.searchQuery,'Tạo Lô/Sê-ri');
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

    async onBarcodeScanned(barcode){
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
        var barcodeData = await this.env.model.parseBarcodeMrp(barcode, false, false, false);
        console.log(barcodeData);
        if (!barcodeData.match) {
            // const message = _t(`Không tìm thấy thông tin của barcode: ${barcode}!`);
            // this.notification.add(message, { type: "warning" });
            let data = await this.orm.call("mrp.production", "create_package", [null, barcode], {});
            if (!data || !data.id) {
                console.error("Lỗi khi tạo package!");
                return;
            }

            let newPackage = { id: data.id, name: data.name };
            
            if (this.props.title === "Đóng Packages loạt") {
                if (!this.state.createPackageQty) {
                    this.state.resultPackages.push(newPackage);
                }
            }

            console.log("Package mới đã tạo:", newPackage);
            return;
        }
    
        if (barcodeData.barcodeType !== "packages") {
            const message = _t(`Barcode: ${barcode} không phải là Packages!`);
            this.notification.add(message, { type: "warning" });
            return;
        }
    
        // Nếu barcode hợp lệ và là "packages"
        let packageInfo = {
            id: barcodeData.record.id,
            name: barcodeData.barcode
        };
    
        let productQty = barcodeData.record.products
            .filter((x) => x.product_id === this.props.move.product_id)
            .reduce((total, prod) => total + prod.available_quantity, 0);
    
        if (this.props.title === "Chia tách Packages") {
            if (!this.state.packageId) {
                this.state.package = barcodeData.record;
                this.state.packageProductQty = productQty;
                this.state.packageName = barcodeData.barcode;
                this.state.packageId = barcodeData.record.id;
            } else if (this.state.packageId !== barcodeData.record.id && !this.state.showPackageQty) {
                this.state.processedPackages.push(packageInfo);
            }
        } 
        else if (this.props.title === "Đóng Packages loạt") {
            if (!this.state.createPackageQty) {
                let findpack = this.state.resultPackages.find((x) => x.id === packageInfo.id);
                if (!findpack) {
                    this.state.resultPackages.push(packageInfo);
                }
                else {
                    const message = _t(`Pack ${packageInfo.name} đã được quét`);
                    this.notification.add(message, { type: "warning" });
                }
                // this.state.resultPackages.push(packageInfo);
                // console.log(this.state.resultPackages)
            }
        }
    }
}
Selector.props = ['records', 'multiSelect?', 'closeSelector','title','isSelector?', 'move?'];
Selector.template = 'Selector'