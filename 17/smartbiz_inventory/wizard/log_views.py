# -*- coding: utf-8 -*-

from odoo import fields, models, api

class InventoryConfirmWizard(models.TransientModel):
    _name = 'smartbiz.inventory.confirm.wizard'
    _description = 'Xác nhận áp dụng kiểm kê'

    inventory_id = fields.Many2one('smartbiz.inventory', string='Phiếu kiểm kê', required=True)
    apply_inventory = fields.Boolean(string="Áp dụng kiểm kê", default=True)
    has_pending_lines = fields.Boolean(string="Có dòng chưa kiểm kê?", compute="_compute_has_pending_lines")

    @api.depends('inventory_id')
    def _compute_has_pending_lines(self):
        for wizard in self:
            pending_lines = wizard.inventory_id.line_ids.filtered(lambda l: l.state != 'counting')
            wizard.has_pending_lines = bool(pending_lines)
    def action_confirm(self):
        """Gọi action_validate để thực hiện kiểm kê"""
        if self.apply_inventory:
            self.inventory_id.action_validate()
            return {'type': 'ir.actions.act_window_close'}
        else:
            return {'type': 'ir.actions.act_window_close'}
        
    def action_confirm_and_create_new(self):
        if self.apply_inventory:
            # Gọi validate nhưng chỉ cho dòng đã đếm
            lines_to_validate = self.inventory_id.line_ids.filtered(lambda l: l.state == 'counting')
            lines_to_validate.write({'state': 'done'})
            
            for line in lines_to_validate:
                self.env['smartbiz.inventory.history'].create({
                    'inventory_id': self.inventory_id.id,
                    'name': self.inventory_id.name,
                    'product_id': line.product_id.id,
                    'lot_id': line.lot_id.id if line.lot_id else False,
                    'package_id': line.package_id.id if line.package_id else False,
                    'location_id': line.location_id.id,
                    'company_id': self.inventory_id.company_id.id,
                    'user_id': self.inventory_id.user_id.id if self.inventory_id.user_id else False,
                    'quantity_before': line.quantity_before,
                    'quantity_after': line.quantity_counted,
                    'difference': line.difference,
                    'date': fields.Datetime.now(),
                    'note': line.note,
                })
            self.inventory_id.state = 'done'

            # Tạo kiểm kê mới cho các dòng chưa kiểm kê
            pending_lines = self.inventory_id.line_ids.filtered(lambda l: l.state == 'pending')
            if pending_lines:
                new_inv = self.env['smartbiz.inventory'].create({
                    'name': self._generate_inventory_name(),
                    'company_id': self.inventory_id.company_id.id,
                    'user_id': self.inventory_id.user_id.id,
                    'inventory_period_id': self.inventory_id.inventory_period_id.id,
                })
                for line in pending_lines:
                    self.env['smartbiz.inventory.line'].create({
                        'inventory_id': new_inv.id,
                        'product_id': line.product_id.id,
                        'lot_id': line.lot_id.id if line.lot_id else False,
                        'package_id': line.package_id.id if line.package_id else False,
                        'location_id': line.location_id.id,
                        'quantity_before': line.quantity_before,
                        'state': 'pending',
                    })
                
                # Xóa các dòng pending trong đơn kiểm kê cũ sau khi đã chuyển sang đơn mới
                pending_lines.unlink()

        return {'type': 'ir.actions.act_window_close'}

    def _generate_inventory_name(self):
        """ Tạo tên cho kiểm kê mới theo định dạng tự động """
        last_inv = self.env['smartbiz.inventory'].search([('company_id', '=', self.inventory_id.company_id.id)],
                                                        order='id desc', limit=1)
        if last_inv:
            # Nếu có đơn kiểm kê trước đó, tăng số cuối cùng lên 1
            last_number = int(last_inv.name.split()[-1])  # Giả sử tên đơn kiểm kê có định dạng '001', '002', ...
            new_number = str(last_number + 1).zfill(3)  # Tăng số và đảm bảo có 3 chữ số
        else:
            # Nếu không có đơn kiểm kê nào trước đó, bắt đầu từ 001
            new_number = '001'
        
        return f"{self.inventory_id.name} - {new_number}"

    def action_cancel(self):
        """Hủy, không làm gì cả"""
        
        return {'type': 'ir.actions.act_window_close'}
    
class InventoryCancelWizard(models.TransientModel):
    _name = 'smartbiz.inventory.cancel.wizard'
    _description = 'Hủy kiểm kê'

    inventory_id = fields.Many2one('smartbiz.inventory', string='Phiếu kiểm kê', required=True)


    def action_confirm(self):
        """Hủy, không làm gì cả"""
        """Gọi action_cancel để thực hiện hủy kiểm kê"""
        
        self.inventory_id.action_cancel()
        return {'type': 'ir.actions.act_window_close'}
    
    def action_cancel(self):
        """Hủy, không làm gì cả"""
        
        return {'type': 'ir.actions.act_window_close'}
