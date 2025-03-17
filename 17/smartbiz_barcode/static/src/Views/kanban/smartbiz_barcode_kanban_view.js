/** @odoo-module */

import { kanbanView } from '@web/views/kanban/kanban_view';
import { registry } from "@web/core/registry";
import { smartbizBarcodeKanbanController } from './smartbiz_barcode_kanban_controller';
import { smartbizBarcodeKanbanRenderer } from './smartbiz_barcode_kanban_renderer';

export const smartbizBarcodeKanbanView = Object.assign({}, kanbanView, {
    Controller: smartbizBarcodeKanbanController,
    Renderer: smartbizBarcodeKanbanRenderer,
});
registry.category("views").add("smartbiz_kanban_barcode", smartbizBarcodeKanbanView);
