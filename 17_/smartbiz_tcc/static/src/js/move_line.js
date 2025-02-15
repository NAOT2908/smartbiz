/** @odoo-module */
import LineComponent from '@stock_barcode/components/line';

LineComponent.prototype.doPrint = async function(ev) {
    try {
        const result = await this.env.services.orm.call('stock.move.line', 'print_label', [[this.line.id]]);
        console.log(result);
    } catch (error) {
        console.error(error);
    }
};
