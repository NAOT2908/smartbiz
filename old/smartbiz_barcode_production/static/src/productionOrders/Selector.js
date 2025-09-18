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
    static props = [
        'records', 
        'multiSelect?', 
        'closeSelector',
        'title',
        'isSelector?', 
        'move?'
    ];
    static template = 'Selector'
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
export class ProductionEntryDialog extends Component {
  static template = "ProductionEntryDialog";
  static props = [
    "closeDialog",
    "mode",                     // 'material' | 'finished'
    "productionId",
    "materialMoves",
    "finishedMoves",
    "moveLines",
    "preProductionPackages",
    "onUpdated?",              // callback(data)
  ];

  setup() {
    this.rpc = useService('rpc');
    this.orm = useService('orm');
    this.notification = useService('notification');
    this.dialog = useService('dialog');
    this.action = useService('action');
    this.barcodeService = useService("barcode");

    this.state = useState({
      processedPackages: [],     // [{id, name, record, lines?}]
      combinedProductData: [],   // [{productId, productName, quantityScanned, quantityNeeded}]
      showDetailsModal: false,
      modalProductData: {},
      needMap: new Map(),        // productId -> needed qty
    });

    useBus(this.barcodeService.bus, "barcode_scanned", (ev) =>
      this.onBarcodeScanned(ev.detail.barcode)
    );

    // chuẩn bị needMap ngay khi mở
    this._buildNeedMap();
	
	
  }

  // ---------- Helpers ----------
  _round(n) { return Math.round((n || 0) * 1000) / 1000; }

  _buildNeedMap() {
    const need = new Map();
    if (this.props.mode === 'material') {
      for (const mv of (this.props.materialMoves || [])) {
        const pid = mv.product_id;
        const plan = mv.product_uom_qty ?? mv.product_qty ?? 0;
        const done = mv.quantity ?? 0;
        const remain = Math.max(this._round(plan - done), 0);
        if (remain > 0) need.set(pid, (need.get(pid) || 0) + remain);
      }
    } else {
      for (const mv of (this.props.finishedMoves || [])) {
        const pid = mv.product_id;
        const plan = mv.product_uom_qty ?? mv.product_qty ?? 0;
        const done = mv.quantity ?? 0;
        const remain = Math.max(this._round(plan - done), 0);
        if (remain > 0) need.set(pid, (need.get(pid) || 0) + remain);
      }
    }
    this.state.needMap = need;
    this._rebuildCombinedProductData();
  }

  _productNameById(pid) {
    // Ưu tiên lấy từ moves
	 
    if (this.props.mode === 'material') {
      const found = (this.props.materialMoves || []).find(m => m.product_id === pid);
      if (found) return found.product_name || '';
    } else {
      const found = (this.props.finishedMoves || []).find(m => m.product_id === pid);
      if (found) return found.product_name || '';
    }
    return '';
  }

  _finishedMoveIdSet() {
    return new Set((this.props.finishedMoves || []).map(m => m.id));
  }

  _existsInPreProduction(pkgId) {
    // kiểm tra có quant nào có package_id == pkgId ở location src
    return (this.props.preProductionPackages || []).some(q => {
      return q.package_id && q.package_id[0] === pkgId;
    });
  }

_findFinishedLinesByPackage(pkgId) {
  const finishedIds = new Set((this.props.finishedMoves || []).map(m => m.id));
  const moveStateMap = this._finishedMoveStateMap();

  return (this.props.moveLines || []).filter((ml) => {
    const isFinishedMove = finishedIds.has(ml.move_id);

    const rpk = ml.result_package_id;
    const rpkId = Array.isArray(rpk) ? rpk[0] : rpk;

    const pk = ml.package_id;
    const pkId = Array.isArray(pk) ? pk[0] : pk;

    const hasPkg = (rpkId === pkgId) || (pkId === pkgId);

    // loại trừ các line đã done hoặc move cha đã done
    const lineIsDone = (ml.state === 'done');
    const parentState = moveStateMap.get(ml.move_id);
    const parentIsDone = (parentState === 'done');

    return isFinishedMove && !!hasPkg && !lineIsDone && !parentIsDone;
  });
}
_findAllFinishedLinesByPackage(pkgId) {
  const finishedIds = new Set((this.props.finishedMoves || []).map(m => m.id));
  return (this.props.moveLines || []).filter((ml) => {
    const isFinishedMove = finishedIds.has(ml.move_id);
    const rpk = ml.result_package_id;
    const rpkId = Array.isArray(rpk) ? rpk[0] : rpk;
    const pk = ml.package_id;
    const pkId = Array.isArray(pk) ? pk[0] : pk;
    const hasPkg = (rpkId === pkgId) || (pkId === pkgId);
    return isFinishedMove && !!hasPkg;
  });
}
  _sumFromPackagesMaterial() {
    // gom theo sản phẩm từ danh sách package đã quét (dựa vào record.products)
    const sums = new Map(); // pid -> total qty scanned
    for (const pkg of this.state.processedPackages) {
      const rec = pkg.record;
      if (!rec || !rec.products) continue;
      for (const p of rec.products) {
        const pid = p.product_id;
        const qty = this._round(p.available_quantity ?? p.quantity ?? 0);
        if (qty > 0) sums.set(pid, (sums.get(pid) || 0) + qty);
      }
    }
    return sums;
  }

  _sumFromPackagesFinished() {
    // gom theo sản phẩm từ chính move line finished (phù hợp yêu cầu)
    const sums = new Map(); // pid -> total qty scanned in selected package-lines
    for (const pkg of this.state.processedPackages) {
      const lines = pkg.lines || [];
      for (const l of lines) {
        const pid = l.product_id;
        const qty = this._round(l.quantity ?? l.qty_done ?? 0);
        if (qty > 0) sums.set(pid, (sums.get(pid) || 0) + qty);
      }
    }
    return sums;
  }

  _rebuildCombinedProductData() {
    const combined = [];
    let scannedMap = new Map();

    if (this.props.mode === 'material') {
      scannedMap = this._sumFromPackagesMaterial();
    } else {
      scannedMap = this._sumFromPackagesFinished();
    }

    // Hợp nhất theo danh sách needMap (sản phẩm cần) + sản phẩm đã quét
    const allPids = new Set([
      ...Array.from(this.state.needMap.keys()),
      ...Array.from(scannedMap.keys()),
    ]);

    for (const pid of allPids) {
      const need = this._round(this.state.needMap.get(pid) || 0);
      const scanned = this._round(scannedMap.get(pid) || 0);
      combined.push({
        productId: pid,
        productName: this._productNameById(pid),
        quantityScanned: scanned,
        quantityNeeded: need,
      });
    }
	console.log(combined)
    // sắp xếp: còn cần nhiều lên trên
    combined.sort((a, b) => (b.quantityNeeded - a.quantityNeeded));
    this.state.combinedProductData = combined;
  }

  // ---------- UI actions ----------
  closeDialog() {
    this.props.closeDialog();
    this.state.processedPackages = [];
    this.state.combinedProductData = [];
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
    if (!barcode) {
      this.notification.add(_t("Vui lòng quét lại!"), { type: "warning" });
      return;
    }
    await this._processBarcode(barcode);
    if ("vibrate" in window.navigator) window.navigator.vibrate(80);
  }

  removeProcessedPackage(pkgId){
    const idx = this.state.processedPackages.findIndex(p => p.id === pkgId);
    if (idx > -1) {
      this.state.processedPackages.splice(idx, 1);
      this._rebuildCombinedProductData();
    }
  }

  openDetailsModal(productId){
	 
    const productName = this._productNameById(productId);
    const rows = [];

    if (this.props.mode === 'material') {
      // từ record.products trong các package đã quét
      for (const pkg of this.state.processedPackages) {
        const rec = pkg.record;
        if (!rec || !rec.products) continue;
        for (const p of rec.products) {
          if (p.product_id === productId) {
            rows.push({
              key: `${pkg.id}-${productId}-${rows.length}`,
              packageName: pkg.name,
              quantity: this._round(p.available_quantity ?? p.quantity ?? 0),
              location: p.location_name || '',
              lot: p.lot_name || '',
            });
          }
        }
      }
    } else {
      // từ move lines đã match theo package
      for (const pkg of this.state.processedPackages) {
        const lines = pkg.lines || [];
        for (const l of lines) {
          if (l.product_id === productId) {
            rows.push({
              key: `${pkg.id}-${productId}-${rows.length}`,
              packageName: pkg.name,
              quantity: this._round(l.quantity ?? l.qty_done ?? 0),
              location: l.location_name || '',
              lot: l.lot_name || '',
            });
          }
        }
      }
    }

    this.state.modalProductData = { productId, productName, packages: rows };
    this.state.showDetailsModal = true;
  }

  closeDialogDetails() {
	
    this.state.showDetailsModal = false;
  }

async _processBarcode(barcode) {
  const barcodeData = await this.env.model.parseBarcodeMrp(barcode, false, false, false);
  console.log(barcodeData)
  if (!barcodeData.match) {
    this.notification.add(_t(`Không tìm thấy thông tin của barcode: ${barcode}!`), { type: "warning" });
    return;
  }
  if (barcodeData.barcodeType !== "packages") {
    this.notification.add(_t(`Barcode: ${barcode} không phải là Packages!`), { type: "warning" });
    return;
  }

  const pkg = {
    id: barcodeData.record.id,
    name: barcodeData.barcode,
    record: barcodeData.record,
  };

  if (this.props.mode === 'material') {
    const ok = this._existsInPreProduction(pkg.id);
    if (!ok) {
      this.notification.add(_t(`Package ${pkg.name} không thuộc khu vực tiền sản xuất (pre_production)!`), { type: "warning" });
      return;
    }
  } else {
    // finished: tìm các line hợp lệ (không done)
    const lines = this._findFinishedLinesByPackage(pkg.id);
    if (!lines.length) {
      // nếu không có line hợp lệ, kiểm lại xem có line nhưng đã done hay không
      const raw = this._findAllFinishedLinesByPackage(pkg.id);
      if (raw.length) {
        this.notification.add(_t(`Package ${pkg.name} đã được ghi nhận xong (done), không thể ghi nhận lại.`), { type: "warning" });
      } else {
        this.notification.add(_t(`Package ${pkg.name} không có trong move line của thành phẩm!`), { type: "warning" });
      }
      return;
    }
    pkg.lines = lines;
  }

  const exists = this.state.processedPackages.find(p => p.id === pkg.id);
  if (exists) {
    this.notification.add(_t(`Package ${pkg.name} đã được quét.`), { type: "info" });
  } else {
    this.state.processedPackages.push(pkg);
    this._rebuildCombinedProductData();
  }
}


  // ---------- Ghi nhận ----------
  async handleRecordProducts() {

      if (!this.state.processedPackages.length) {
        this.notification.add(_t("Chưa có package nào được quét."), { type: "warning" });
        return;
      }

      if (this.props.mode === 'material') {
        await this._recordMaterial();
      } else {
        await this._recordFinished();
      }

      // Post các dòng đã chuẩn bị
      const post = await this.orm.call(
        "mrp.production",
        "button_post_prepared_lines",
        [, this.props.productionId],
        {}
      );

      // Refresh parent
      if (this.props.onUpdated) this.props.onUpdated(post);

      this.notification.add(_t("Ghi nhận thành công."), { type: "success" });
      this.closeDialog();
 
    }
	_finishedMoveStateMap() {
	  const map = new Map();
	  (this.props.finishedMoves || []).forEach(mv => {
		map.set(mv.id, mv.state); // ví dụ: 'done', 'assigned', ...
	  });
	  return map;
	}

  // Tạo move line tiêu thụ từ các package quét (material)
  async _recordMaterial() {
    // build remain map theo move (cho phép phân bổ đúng nhu cầu từng move)
    const remainByMove = new Map(); // move_id -> remain qty
    const movesByProduct = new Map(); // product_id -> [move...]
    for (const mv of (this.props.materialMoves || [])) {
      const plan = mv.product_uom_qty ?? mv.product_qty ?? 0;
      const done = mv.quantity ?? 0;
      const remain = Math.max(this._round(plan - done), 0);
      if (remain > 0) {
        remainByMove.set(mv.id, remain);
        const arr = movesByProduct.get(mv.product_id) || [];
        arr.push(mv);
        movesByProduct.set(mv.product_id, arr);
      }
    }

    // Duyệt từng package đã quét
    for (const pkg of this.state.processedPackages) {
      const rec = pkg.record;
      if (!rec || !rec.products) continue;

      for (const p of rec.products) {
        const pid = p.product_id;
        const available = this._round(p.available_quantity ?? p.quantity ?? 0);
        if (available <= 0) continue;

        const moves = movesByProduct.get(pid) || [];
        let remainAvailable = available;

        for (const mv of moves) {
          if (remainAvailable <= 0) break;
          const mvRemain = remainByMove.get(mv.id) || 0;
          if (mvRemain <= 0) continue;

          const take = this._round(Math.min(mvRemain, remainAvailable));
          if (take <= 0) continue;

          const line = {
            id: false,
            move_id: mv.id,
            product_id: pid,
            product_name: mv.product_name || "",
            location_id: p.location_id || mv.location_id,               // nguồn: từ package/quant
            location_name: p.location_name || "",
            location_dest_id: mv.location_dest_id,                      // đích: theo move
            location_dest_name: mv.location_dest_name || "",
            product_uom_id: mv.product_uom_id,
            product_uom_qty: mv.product_uom_qty || 0,
            qty_done: take,
            quantity: take,
            tracking: mv.product_tracking,
            lot_id: p.lot_id || null,
            lot_name: p.lot_name || "",
            package_id: pkg.id,                                         // package nguồn
            package_name: pkg.name,
            result_package_id: null,
            result_package_name: "",
            picked: true,                                               // đánh dấu chuẩn bị
          };

          await this.orm.call(
            "mrp.production",
            "save_order",
            [, this.props.productionId, line],
            {}
          );

          // cập nhật còn lại
          remainAvailable = this._round(remainAvailable - take);
          remainByMove.set(mv.id, this._round(mvRemain - take));
        }
      }
    }
  }

  // Đặt picked cho các move line thành phẩm theo package đã quét
  async _recordFinished() {
    // Lọc move line thuộc finished đã được gắn ở _processBarcode
    for (const pkg of this.state.processedPackages) {
      const lines = pkg.lines || [];
      for (const l of lines) {
        const rp = l.result_package_id;
		const rpId = Array.isArray(rp) ? rp[0] : rp;
		const rpName = Array.isArray(rp) ? rp[1] : (l.result_package_name || "");

		const upd = {
		  id: l.id,
		  move_id: l.move_id,
		  product_id: l.product_id,
		  product_name: l.product_name,
		  location_id: l.location_id,
		  location_name: l.location_name || "",
		  location_dest_id: l.location_dest_id,
		  location_dest_name: l.location_dest_name || "",
		  product_uom_id: l.product_uom_id,
		  product_uom_qty: l.product_uom_qty || 0,
		  qty_done: l.quantity || l.qty_done || 0,
		  quantity: l.quantity || l.qty_done || 0,
		  tracking: l.product_tracking,
		  lot_id: l.lot_id || null,
		  lot_name: l.lot_name || "",
		  package_id: l.package_id || null,
		  package_name: l.package_name || "",
		  result_package_id: rpId || null,
		  result_package_name: rpName,
		  picked: true,
		};

        await this.orm.call(
          "mrp.production",
          "save_order",
          [, this.props.productionId, upd],
          {}
        );
      }
    }
  }
}
