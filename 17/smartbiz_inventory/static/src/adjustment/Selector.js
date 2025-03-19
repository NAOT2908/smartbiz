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
            product_id: this.props.records.product_id,
            package_id: this.props.records.package_id,
            lot_name: this.props.records.lot_name,
            lot_id: this.props.records.lot_id,
            
        });

        // console.log(this.props.isSelector, this.props.records)
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
            "smartbiz.inventory",
            this.inventory_id,
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
        // console.log(recordId)
        const index = this.state.selectedRecords.indexOf(recordId);
        if (this.props.multiSelect) {
            if (index > -1) {
                this.state.selectedRecords.splice(index, 1); // Remove if already selected
            } else {
                this.state.selectedRecords.push(recordId); // Add to selection
            }
        } else {
                if(this.state.selectedRecord == recordId)
                    this.state.selectedRecord = 0
                else
                    this.state.selectedRecord = recordId
        }
    }

    roundToTwo(num) {
        return Math.round(num * 100) / 100;
    }
    

    async confirmSelection() {
        if(this.props.isSelector){
            if(this.props.title == "Sản phẩm"){
                this.props.closeSelector(this.state.records.find(x=>x.id == this.state.selectedRecord),'Sản phẩm');
            }
            else if(this.props.title == "Chọn vị trí"){
                this.props.closeSelector(this.state.records.find(x=>x.id == this.state.selectedRecord),'Chọn vị trí');
            }
            else if(this.props.title == "Chọn số Lô/Sê-ri"){
                this.props.closeSelector(this.state.records.find(x=>x.id == this.state.selectedRecord),'Chọn số Lô/Sê-ri');
            }
            else if(this.props.title == "Chọn kiện hàng"){
                this.props.closeSelector(this.state.records.find(x=>x.id == this.state.selectedRecord),'Chọn kiện hàng');
            }
            else
            {
                this.props.closeSelector(this.state.selectedRecords);
            } 
        } else {
            console.log("Không có gì")
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
            const message = _t(`Không tìm thấy thông tin của barcode: ${barcode}!`);
            this.notification.add(message, { type: "warning" });
            
        }
    
        if (barcodeData.barcodeType !== "packages") {
            const message = _t(`Barcode: ${barcode} không phải là Packages!`);
            this.notification.add(message, { type: "warning" });
            return;
        }
    
        
    }
}
Selector.props = ['records', 'multiSelect?', 'closeSelector','title','isSelector?'];
Selector.template = 'SelectItem'