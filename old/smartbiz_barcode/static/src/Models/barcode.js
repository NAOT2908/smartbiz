/** @odoo-module **/

import { BarcodeParser } from "@barcodes/js/barcode_parser";
import { Mutex } from "@web/core/utils/concurrency";
import BarcodeCache from './cache';
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { FNC1_CHAR } from "@barcodes_gs1_nomenclature/js/barcode_parser";
import { EventBus } from "@odoo/owl";

export default class SmartBizBarcodeModel extends EventBus {
    constructor(resModel, resId, services) {
        super();
        this.dialogService = useService('dialog');
        this.orm = services.orm;
        this.rpc = services.rpc;
        this.notificationService = services.notification;
        this.action = services.action;
        this.resId = resId;
        this.resModel = resModel;
        this.barcodeFieldByModel = {
            'stock.location': 'barcode',
            'product.product': 'barcode',
            'stock.package.type': 'barcode',
            'hr.employee': 'barcode',
            'stock.picking': 'name',
            'stock.quant.package': 'name',
            'stock.lot': 'name', // Also ref, should take in account multiple fields ?
        };
        this.dataTypes = ['products','locations','lots','packages']
        // Keeps the history of all barcodes scanned (start with the most recent.)
        this.scanHistory = [];
        // Keeps track of list scanned record(s) by type.
        this.lastScanned = { packageId: false, product: false, sourceLocation: false };
        this._currentLocation = false; // Reminds the current source when the scanned one is forgotten.
        this.needSourceConfirmation = false;
        this.nomenclature = null;
        
    }
    setup()
    {
        this.parser = new BarcodeParser({nomenclature: this.nomenclature});
    }
    

    async parseBarcode(barcode,filters=false,cacheOnly=false,barcodeType=false) {

        var result = {
            barcode,
            match:false,
            barcodeType:barcodeType,
            fromCache:true
        }
        console.log(result)
        if(barcodeType)
        {
            if (barcodeType == "lots")
            {
                var record = this.data.find(x=>x.name == barcode && x.product_id.id == filters['product_id'])
            }
            else if(barcodeType == "products" || barcodeType == "locations" )
            {
                var record = this.data.find(x=>x.barcode == barcode)
            }
            else
            {
                var record = this.data.find(x=>x.name == barcode)
            }
            if(record)
            {
                result.match = true;
                result.record = record
                return result;
            }
            
        }
        else
        {
            var productData = this.data['products'].find(x=>x.barcode == barcode)
            if (productData)
            {
                result.match = true;
                result.barcodeType = "products"
                result.record = productData
                return result;
            }
            var packageData = this.data['packages'].find(x=>x.name == barcode)
            if (packageData)
            {
                result.match = true;
                result.barcodeType = "packages"
                result.record = packageData
                return result;
            }
            var locationData = this.data['locations'].find(x=>x.barcode == barcode)
            if (locationData)
            {
                result.match = true;
                result.barcodeType = "locations"
                result.record = locationData
                return result;
            }
            if(filters)
            {
                var lotData = this.data['lots'].find(x=>x.name == barcode && x.product_id.id == filters['product_id'])
                if (lotData)
                {
                    result.match = true;
                    result.barcodeType = "lots"
                    result.record = lotData
                    return result;
                }
            }
            
        }
        
        if (!cacheOnly)
        {
            return await this.orm.call('stock.picking', 'get_barcode_data', [,barcode,filters,barcodeType],{});
        }
        result.record = false
        return result
    }
    async parseBarcodeForInventory(barcode, filters = false, cacheOnly = false, barcodeType = false) {
        let result = {
            barcode,
            match: false,
            barcodeType: barcodeType,
            record: null,
        };
    
        // console.log( "result:", result);
        // Nếu không tìm thấy trong cache và cacheOnly = false, gọi API backend
        if (!cacheOnly) {
            try {
                
                const backendResult = await this.orm.call('smartbiz.inventory', 'get_inventory_barcode_data',
                    [,barcode, filters, barcodeType]
                );
                // console.log(backendResult)
                if (backendResult?.match) {
                    return backendResult;
                }
            } catch (error) {
                console.error("Error calling backend API:", error);
            }
        }
    
        // Trả về kết quả mặc định nếu không tìm thấy
        result.record = false;
        return result;
    }
    async parseBarcodeMrp(barcode,filters=false,cacheOnly=false,barcodeType=false) {

        var result = {
            barcode,
            match:false,
            barcodeType:barcodeType,
            fromCache:true
        }
        console.log(result)
        
        
        if (!cacheOnly)
        {
            return await this.orm.call('mrp.production', 'get_barcode_data', [,barcode,filters,barcodeType],{});
        }
        result.record = false
        return result
    }
    async parseBarcodeForWorkcenter(barcode, filters = false, cacheOnly = false, barcodeType = false) {
        let result = {
            barcode,
            match: false,
            barcodeType:barcodeType,
            fromCache:true,
        };
    
        console.log("Barcode input:", barcode);
        // Gọi API backend nếu không chỉ tìm trong cache
        if (!cacheOnly) {
            try {
                const backendResult = await this.orm.call(
                    'mrp.workcenter', // Model
                    'get_barcode_data',      // Method name
                    [,barcode, filters, barcodeType], // Arguments
                    {}
                );
                console.log("Backend result:", backendResult);
                if (backendResult?.match) {
                    return backendResult;
                }
            } catch (error) {
                console.error("Error fetching workcenter data:", error);
            }
        }
    
        // Trả về kết quả mặc định nếu không tìm thấy
        result.record = false;
        return result;
    }    
    
}