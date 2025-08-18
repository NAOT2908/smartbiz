/** @odoo-module */

import { kanbanView } from '@web/views/kanban/kanban_view';
import { registry } from "@web/core/registry";
import { MrpBarcodeKanbanController } from './barcode_kanban_controller';
import { MrpBarcodeKanbanRenderer } from './barcode_kanban_renderer';

export const mrpBarcodeKanbanView = Object.assign({}, kanbanView, {
    Controller: MrpBarcodeKanbanController,
    Renderer: MrpBarcodeKanbanRenderer,
});
registry.category("views").add("mrp_kanban_barcode", mrpBarcodeKanbanView);
