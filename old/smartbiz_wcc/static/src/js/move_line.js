// /** @odoo-module */
// import LineComponent from '@stock_barcode/components/line';
// import BarcodePickingModel from '@stock_barcode/models/barcode_picking_model';

// function roundToTwo(num) {
//     return Math.round(num * 100) / 100;
// }

// LineComponent.prototype.doPrint = async function(ev) {
//     try {
//         const result = await this.env.services.orm.call('stock.move.line', 'print_label', [[this.line.id]]);
//         console.log(result);
//     } catch (error) {
//         console.error(error);
//     }
// };
// BarcodePickingModel.prototype.splitLine = async function(line) {
//     if (!this.shouldSplitLine(line)) {
//         return false;
//     }
//     // Gives the line's destination to the new line (the picking destination is used otherwise.)
//     const fieldsParams = { location_dest_id: line.location_dest_id.id };
//     const newLine = await this._createNewLine({ copyOf: line, fieldsParams });
//     // Update the reservation of the both old and new lines.
//     newLine.reserved_uom_qty = roundToTwo(line.reserved_uom_qty - line.qty_done);
//     //Thêm vào để cho số lượng còn lại
//     newLine.qty_done = roundToTwo(line.reserved_uom_qty - line.qty_done);
//     newLine.picked = false;
//     line.reserved_uom_qty = line.qty_done;
//     // Be sure the new line has no lot by default.
//     newLine.lot_id = false;
//     newLine.lot_name = false;

//     return newLine;
// }
