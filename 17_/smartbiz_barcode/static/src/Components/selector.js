/** @odoo-module **/
import { Component, useState, xml } from '@odoo/owl';
import { registry } from "@web/core/registry";
import { useService,useBus } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { ManualBarcodeScanner } from "./manual_barcode";
import * as BarcodeScanner from "@web/webclient/barcode/barcode_scanner";
export class Selector extends Component {
    setup() {
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
            
            lot_name: this.props.move.lot_name || ''

        });
        this.barcodeService = useService("barcode");
        useBus(this.barcodeService.bus, "barcode_scanned", (ev) =>
            this.onBarcodeScanned(ev.detail.barcode)
          );
        if (this.props.title === 'Chọn số Lô/Sê-ri' || this.props.title === 'Chọn kiện đích') {
            this.state.showCreateNew = true;
        }
    }
    willUpdateProps(nextProps) {
       this.state.barcodeData = nextProps.barcodeData
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
    async processBarcode(barcode){
        var barcodeData = await this.env.model.parseBarcode(
            barcode,
            false,
            false,
            false
        );
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
            else{            
                const message = _t(`Barcode: ${barcode} không phải là Packages!`);
                this.notification.add(message, { type: "warning" });
            }
        } else {
            
            const message = _t(`Không có thấy thông tin của barcode: ${barcode}!`);
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
            if (this.props.title === "Chọn sản phẩm") {
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
                let qtyPerPackage = parseFloat(this.state.qtyPerPackage);
                let packageQty = parseInt(this.state.packageQty);

                if (isNaN(qtyPerPackage) || isNaN(packageQty) || qtyPerPackage <= 0 || packageQty <= 0) {
                    this.notification.add(_t("Vui lòng nhập số lượng hợp lệ cho số lượng trên một pack và số pack."), { type: "warning" });
                    return;
                }

                let lotName = this.state.lot_name.trim();
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
                this.props.closeSelector(lines);
            }
        
            
            
        }
           
        
    }

    cancelSelection() {
        this.props.closeSelector(false);
    }
    async editRecord(id){
        if (this.props.title === "Chọn kiện đích") {
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
        if (this.props.title === "Chọn kiện đích") {
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
    
    roundToTwo(num) {
        return Math.round(num * 100) / 100;
    }
    
    
}

Selector.props = ['records', 'multiSelect?', 'closeSelector', 'title','move?','isSelector?','lots?'];
Selector.template = xml`
<div class="s_selector-modal">
    <div class="s_selector-modal-content">
        <div class="s_selector-header">
            <h2><t t-esc="props.title" /></h2>
            <i class="fa fa-barcode" t-on-click="openManualScanner"/>
        </div>
        <t t-if="props.isSelector">
            <input t-model="state.searchQuery" placeholder="Tìm kiếm..." class="s_selector-search-input"/>
            <input t-model="state.quantity" t-if="props.title == 'Chọn sản phẩm'" placeholder="Nhập số lượng sản phẩm" class="s_selector-search-input"/>
            <ul class="s_selector-record-list">
                <t t-foreach="filteredRecords" t-as="record" t-key="record.id">
                    <li t-on-click="()=>this.selectRecord(record.id)" t-att-class="{'s_selector-selected': state.selectedRecords.includes(record.id)}">
                        <span class="record-name"><t t-esc="record.display_name || record.name"/></span>
                        <span class="record-name"><t t-esc="record.origin || ''"/></span>
                        <span t-if="state.selectedRecords.includes(record.id) || state.selectedRecord == record.id" ><i class="fa fa-pencil" t-on-click="() => this.editRecord(record.id)"></i></span>
                        <span t-if="state.selectedRecords.includes(record.id) || state.selectedRecord == record.id" class="record-checkmark">&#10003;</span>
                    </li>
                </t>
            </ul>
        </t>
        <t t-if="props.isSelector == false &amp;&amp; props.title == 'Chia tách Packages'">
            <div class="package-info">
                <div class="package-info-item">
                    <label for="packageName">Package Nguồn:</label>
                    <div t-esc="state.packageName" id="packageName" class="s_selector-info-output"></div>
                </div>
                <div class="package-info-item">
                    <label for="packageProductQty">Số lượng hiện tại:</label>
                    <div t-esc="state.packageProductQty" id="packageProductQty" class="s_selector-info-output"></div>
                </div>
                
                <div class="package-info-item">
                    <label for="qtyPerPackage">Số lượng sản phẩm trong một Package:</label>
                    <input t-model="state.qtyPerPackage" id="qtyPerPackage"  class="s_selector-search-input"/>
                </div>
                <!-- Toggle Switch True/False -->
                <div class="package-info-item">
                    <label for="showPackageQty">Tạo Package mới?</label>
                    <label class="switch">
                        <input type="checkbox" t-model="state.showPackageQty" id="showPackageQty" />
                        <span class="slider round"></span>
                    </label>
                    
                </div>
                <!-- Conditional content based on the switch value -->
                <div t-if="state.showPackageQty">
                    <div class="package-info-item">
                        <label for="packageQty">Số lượng Package mới:</label>
                        <input t-model="state.packageQty" id="packageQty" class="s_selector-search-input"/>
                    </div>
                </div>
                <div t-if="!state.showPackageQty">
                    <div class="package-info-item">
                        <label>Danh sách các Package đích:</label>
                        <div class="package-tags">
                            <t t-foreach="state.processedPackages" t-as="package" t-key="package.id">
                                <span class="package-tag"><t t-esc="package.name" /></span>
                            </t>
                        </div>
                    </div>
                </div>
            </div>
        </t>
        <t t-if="props.isSelector == false and props.title == 'Đóng Packages loạt'">
            <div class="package-info">
                <div class="package-info-item">
                    <label for="productName">Tên sản phẩm:</label>
                    <div t-esc="props.move.product_name" id="productName" class="s_selector-info-output"></div>
                </div>
                <t t-if="props.move.product_tracking !== 'none'">
                    <div class="package-info-item">
                        <label for="lotName">Số lô:</label>
                        <!-- Input field for lot number -->
                        <input t-model="state.lot_name" id="lotName" class="s_selector-search-input"/>
                    </div>
                </t>
                <div class="package-info-item">
                    <label for="remainingQty">Nhu cầu còn lại:</label>
                    <div t-esc="this.roundToTwo(props.move.product_uom_qty - props.move.quantity)" id="remainingQty" class="s_selector-info-output"></div>
                </div>
                <div class="package-info-item">
                    <label for="qtyPerPackage">Số lượng trên một pack:</label>
                    <input t-model="state.qtyPerPackage" id="qtyPerPackage" class="s_selector-search-input"/>
                </div>
                <div class="package-info-item">
                    <label for="packageQty">Số pack:</label>
                    <input t-model="state.packageQty" id="packageQty" class="s_selector-search-input"/>
                </div>
            </div>
        </t>
        <div class="s_selector-action-buttons">
            <button t-on-click="createNew" t-if="state.showCreateNew &amp;&amp; state.selectedRecord == 0">Tạo Mới</button>
            <button t-on-click="confirmSelection" t-if="state.selectedRecord != 0 || state.selectedRecords">Đồng ý</button>           
            <button t-on-click="cancelSelection">Hủy</button>       
        </div>
    </div>
</div>
`;
