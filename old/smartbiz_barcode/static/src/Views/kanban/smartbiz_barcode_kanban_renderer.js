/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { KanbanRenderer } from '@web/views/kanban/kanban_renderer';
import { useService } from '@web/core/utils/hooks';
import * as BarcodeScanner from '@web/webclient/barcode/barcode_scanner';
import { ManualBarcodeScanner } from '@smartbiz_barcode/Components/manual_barcode';
import { onWillStart } from "@odoo/owl";

export class smartbizBarcodeKanbanRenderer extends KanbanRenderer {
    setup() {
        super.setup(...arguments);
        const user = useService('user');
        this.dialog = useService('dialog');
        this.barcodeService = useService('barcode');
        this.display_protip = this.props.list.resModel === 'stock.picking';
        onWillStart(async () => {
            this.packageEnabled = await user.hasGroup('stock.group_tracking_lot');
            this.isMobileScanner = BarcodeScanner.isBarcodeScannerSupported();
        });
    }

    async openMobileScanner() {
        const barcode = await BarcodeScanner.scanBarcode(this.env);
        if (barcode) {
            this.barcodeService.bus.trigger('barcode_scanned', { barcode });
            if ('vibrate' in window.navigator) {
                window.navigator.vibrate(100);
            }
        } else {
            this.env.services.notification.add(
                _t("Please, Scan again!"),
                {type: 'warning'}
            );
        }
    }

    openManualScanner() {
        this.dialog.add(ManualBarcodeScanner, {
            openMobileScanner: async () => {
                await this.openMobileScanner();
            },
            onApply: (barcode) => {   
                this.barcodeService.bus.trigger('barcode_scanned', { barcode });
                if ('vibrate' in window.navigator) {
                    window.navigator.vibrate(100);
                }
            }
        });
    }

}
smartbizBarcodeKanbanRenderer.template = 'smartbiz_barcode.KanbanRenderer';
