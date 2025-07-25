# -*- coding: utf-8 -*-

from odoo import fields, models, api

class InventoryQuantSelectWizard(models.TransientModel):
    _name = 'smartbiz.inventory.quant.wizard'
    _description = 'Chọn dòng kiểm kê từ tồn kho'

    inventory_id = fields.Many2one('smartbiz.inventory', required=True)

    def action_add_lines(self):
    # self sẽ là recordset của các stock.quant được chọn
        active_ids = self.env.context.get('active_ids', [])
        vals_list = []
        selected_quants = self.env['stock.quant'].browse(active_ids)
        for quant in selected_quants:
            vals_list.append({
                'inventory_id': self.inventory_id.id,
                'product_id': quant.product_id.id,
                'lot_id': quant.lot_id.id if quant.lot_id else False,
                'package_id': quant.package_id.id if quant.package_id else False,
                'location_id': quant.location_id.id,
                'company_id': self.inventory_id.company_id.id,
                'quantity': quant.quantity,
                'quantity_counted': 0 if self.inventory_id.set_count == 'empty' else quant.quantity,
                'quant_id': quant.id,
                'note': '',
            })    
    
        self.env['smartbiz.inventory.line'].create(vals_list)
        return {'type': 'ir.actions.act_window_close'}