# -*- coding: utf-8 -*-

from odoo import fields, models

class InventoryConfirmWizard(models.TransientModel):
    _name = 'smartbiz.inventory.confirm.wizard'
    _description = 'Xác nhận áp dụng kiểm kê'

    inventory_id = fields.Many2one('smartbiz.inventory', string='Phiếu kiểm kê', required=True)
    apply_inventory = fields.Boolean(string="Áp dụng kiểm kê", default=True)

    def action_confirm(self):
        """Gọi action_validate để thực hiện kiểm kê"""
        if self.apply_inventory:
            self.inventory_id.action_validate()
            return {'type': 'ir.actions.act_window_close'}
        else:
            return {'type': 'ir.actions.act_window_close'}

    def action_cancel(self):
        """Hủy, không làm gì cả"""
        return {'type': 'ir.actions.act_window_close'}
