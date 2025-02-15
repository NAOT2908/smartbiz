/** @odoo-module */

import { KanbanController } from '@web/views/kanban/kanban_controller';
import { useBus, useService } from '@web/core/utils/hooks';
import { onMounted } from "@odoo/owl";

export class MrpBarcodeKanbanController extends KanbanController {
    setup() {
        super.setup(...arguments);
        this.barcodeService = useService('barcode');
        useBus(this.barcodeService.bus, 'barcode_scanned', (ev) => this._onBarcodeScannedHandler(ev.detail.barcode));
        onMounted(() => {
            document.activeElement.blur();
        });
    }

    openRecord(record) {
        console.log({record,resModel:record.resModel})
        if(record.resModel == 'mrp.production')
            {
                // console.log('oke')
                this.actionService.doAction('smartbiz_barcode_production.stock_pop_action', {
                    additionalContext: { active_id: record.resId,resModel: record.resModel
                     },
                });
            }
    }
    
    async createRecord() {
        if (this.props.resModel === 'mrp.production')
            {
                const id = await this.model.orm.call(
                    'mrp.production',
                    'open_new_production_barcode',
                    [], { context: this.props.context }
                );
                if (id) {
                    return this.actionService.doAction('smartbiz_barcode_production.mrp_production_action', {
                        additionalContext: { active_id: id,resModel: this.props.resModel
                         },
                    });
                }
            }
        return super.createRecord(...arguments);
    }

    // --------------------------------------------------------------------------
    // Handlers
    //--------------------------------------------------------------------------

    /**
     * Called when the user scans a barcode.
     *
     * @param {String} barcode
     */
    async _onBarcodeScannedHandler(barcode) {
        // if (this.props.resModel != 'mrp.production') {
        //     return;
        // }
        const kwargs = { barcode, context: this.props.context };
        const res = await this.model.orm.call(this.props.resModel, 'filter_base_on_barcode', [], kwargs);
        if (res.action) {
            this.actionService.doAction(res.action);
        } else if (res.warning) {
            const params = { title: res.warning.title, type: 'danger' };
            this.model.notification.add(res.warning.message, params);
        }
    }
}
