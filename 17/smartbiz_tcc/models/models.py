# -*- coding: utf-8 -*-

from odoo.osv import expression
from odoo import models, fields, api, exceptions,_, tools
import os
import base64,pytz,logging
from datetime import datetime, timedelta
import datetime as date_time
import random
from odoo.exceptions import UserError, ValidationError
_logger = logging.getLogger(__name__)
from io import BytesIO
import xlsxwriter
from openpyxl import load_workbook
class RES_Partner(models.Model):
    _inherit = ['res.partner']
    customer = fields.Boolean(string='Customer')
    supplier = fields.Boolean(string='Supplier')


    @api.model
    def check_access_rights(self, operation, raise_exception=True):
        if self.env.su:
            return True
        permissions = [{'group':'smartbiz_tcc.group_roles_lien_he___chi_doc_9','read':True,'write':False,'create':False,'unlink':False },]
        if any(self.env.user.has_group(perm['group']) for perm in permissions):
            return any(self.env.user.has_group(perm['group']) and perm[operation] for perm in permissions)
        return super().check_access_rights(operation, raise_exception=raise_exception)
class Sale_OrderLine(models.Model):
    _inherit = ['sale.order.line']
    tc_cost = fields.Float(string='TC Cost', compute='_compute_tc_cost', store=True, groups="smartbiz_tcc.group_roles_ban_hang___bao_cao_day_du_1")
    tc_margin = fields.Float(string='TC Margin', compute='_compute_tc_margin', store=True, groups="smartbiz_tcc.group_roles_ban_hang___bao_cao_day_du_1")
    ppd_cost = fields.Float(string='PPD Cost', compute='_compute_ppd_cost', store=True)
    ppd_margin = fields.Float(string='PPD Margin', compute='_compute_ppd_margin', store=True)
    sales_team_id = fields.Many2one('crm.team', string='Sales Team', compute='_compute_sales_team_id', store=True)
    ppd_price = fields.Float(string='PPD Price')
    lots = fields.Many2many('stock.lot', string='Lots')
    remain_quantity = fields.Float(string='Remain Quantity', compute='_compute_remain_quantity', store=False)
    note = fields.Char(string='Note')


    @api.depends('product_id', 'product_uom_qty')
    def _compute_tc_cost(self):
        for record in self:     
            record.tc_cost = record.product_id.standard_price * record.product_uom_qty

    @api.depends('price_subtotal', 'tc_cost')
    def _compute_tc_margin(self):
        for record in self:     
            record.tc_margin = record.price_subtotal - record.tc_cost

    @api.depends('ppd_price', 'product_uom_qty')
    def _compute_ppd_cost(self):
        for record in self:     
            record.ppd_cost = record.ppd_price * record.product_uom_qty

    @api.depends('ppd_price', 'price_subtotal')
    def _compute_ppd_margin(self):
        for record in self:     
            record.ppd_margin = record.price_subtotal - record.ppd_cost

    @api.depends('order_id')
    def _compute_sales_team_id(self):
        for record in self:  
            record.sales_team_id = record.order_id.team_id

    @api.depends('product_id', 'product_uom_qty')
    def _compute_remain_quantity(self):
        for record in self:  
            reservation = self.env['tcc.reserve'].search([
                    ('product_id','=',record.product_id.id),
                    ('sale_team_id','=',record.order_id.team_id.id),
                    ('reserve_period_id','=',record.order_id.reserve_period_id.id),
                    ('warehouse_id','=',record.order_id.warehouse_id.id)
                ],limit=1)
            record.remain_quantity = reservation.remain_quantity or 0

    @api.onchange('product_id')
    def _update_ppd_price(self):
        for record in self:
            record.ppd_price = record.product_id.list_price

class Sale_Order(models.Model):
    _inherit = ['sale.order']
    partner_id = fields.Many2one('res.partner', store='True', domain=[('customer', '=', True)])
    reserve_period_id = fields.Many2one('tcc.reserve_period', string='Reserve Period', required=True)


    def action_confirm(self):
        if self.env.user.has_group('smartbiz_tcc.group_roles_ban_hang___xac_nhan_don_ban_2'):
            for line in self.order_line:
                if line.product_uom_qty - line.remain_quantity > 0.1 and line.product_id.detailed_type == 'product':
                    # Nếu số lượng nhỏ hơn số lượng còn lại, hiển thị lỗi
                    raise ValidationError(_("Số lượng của sản phẩm '%s' trong đơn hàng lớn hơn số lượng còn lại. Vui lòng kiểm tra lại.") % (line.product_id.display_name))
            res =  super(Sale_Order, self).action_confirm()
            for pk in self.picking_ids:
                pk.write({'sale_team_id':self.team_id.id,'reserve_period_id': self.reserve_period_id.id})
            for line in self.order_line:
                # Tìm các stock moves liên quan đến dòng đơn hàng này
                related_moves = self.env['stock.move'].search([('sale_line_id', '=', line.id)])
                self._update_move_data(related_moves,line.lots.ids,line.note)

            return res

        raise UserError('Bạn không có quyền để thực hiện tác vụ này.')

    def _update_move_data(self,moves,lots,note):
        for move in moves:
            move.write({'lots': lots,'note':note})
            self._update_move_data(move.move_orig_ids,lots,note)

class Purchase_Order(models.Model):
    _inherit = ['purchase.order']
    partner_id = fields.Many2one('res.partner', store='True', domain=[('supplier', '=', True)])


    def button_confirm(self):
        if self.env.user.has_group('smartbiz_tcc.group_roles_mua_hang___xac_nhan_don_mua_11'):
            return super().button_confirm()
        raise UserError('Bạn không có quyền để thực hiện tác vụ này.')

class Purchase_OrderLine(models.Model):
    _inherit = ['purchase.order.line']
    product_id = fields.Many2one('product.product', store='True')


class Product_Product(models.Model):
    _inherit = ['product.product']
    begin_quantity = fields.Float(string='Begin Quantity', compute='_compute_begin_quantity', store=False)
    begin_weight = fields.Float(string='Begin Weight', compute='_compute_begin_weight', store=False)
    begin_ppd_value = fields.Float(string='Begin PPD Value', compute='_compute_begin_ppd_value', store=False)
    begin_value = fields.Float(string='Begin Value', compute='_compute_begin_value', store=False, groups="smartbiz_tcc.group_roles_kho___bao_cao_day_du_7")
    in_quantity = fields.Float(string='In Quantity', compute='_compute_in_quantity', store=False)
    in_weight = fields.Float(string='In Weight', compute='_compute_in_weight', store=False)
    out_ppd_value = fields.Float(string='Out PPD Value', compute='_compute_out_ppd_value', store=False)
    out_value = fields.Float(string='Out Value', compute='_compute_out_value', store=False, groups="smartbiz_tcc.group_roles_kho___bao_cao_day_du_7")
    out_quantity = fields.Float(string='Out Quantity', compute='_compute_out_quantity', store=False)
    out_weight = fields.Float(string='Out Weight', compute='_compute_out_weight', store=False)
    in_ppd_value = fields.Float(string='In PPD Value', compute='_compute_in_ppd_value', store=False)
    in_value = fields.Float(string='In Value', compute='_compute_in_value', store=False, groups="smartbiz_tcc.group_roles_kho___bao_cao_day_du_7")
    end_quantity = fields.Float(string='End Quantity', compute='_compute_end_quantity', store=False)
    end_weight = fields.Float(string='End Weight', compute='_compute_end_weight', store=False)
    end_value = fields.Float(string='End Value', compute='_compute_end_value', store=False, groups="smartbiz_tcc.group_roles_kho___bao_cao_day_du_7")
    end_ppd_value = fields.Float(string='End PPD Value', compute='_compute_end_ppd_value', store=False)
    standard_price = fields.Float(store='True', groups="smartbiz_tcc.group_roles_kho___bao_cao_co_ban_13")


    @api.depends('qty_available')
    def _compute_begin_quantity(self):
        for record in self:
            record.begin_quantity = record.qty_available + record.out_quantity - record.in_quantity

    @api.depends('qty_available')
    def _compute_begin_weight(self):
        for record in self:
            record.begin_weight = record.begin_quantity * record.weight

    @api.depends('qty_available')
    def _compute_begin_ppd_value(self):
        for record in self:
            record.begin_ppd_value = record.list_price * record.begin_quantity

    @api.depends('qty_available')
    def _compute_begin_value(self):
        for record in self:
            record.begin_value = record.standard_price * record.begin_quantity

    @api.depends('qty_available')
    def _compute_in_quantity(self):
        for record in self:
            domain = []
            from_date = self._context.get('from_date')
            to_date = self._context.get('to_date')
            warehouse = self._context.get('warehouse')
            if warehouse:
                domain = [('location_dest_id.warehouse_id', '=', warehouse),('location_usage', '!=',  'internal'),('location_dest_usage', '=', 'internal')]
            else:
                domain = [('location_usage', 'not in',  ('internal','transit')),('location_dest_usage', 'in', ('internal','transit'))]
            domain = domain + [('product_id', '=', record.id),('date', '>=', from_date),('date', '<', to_date),('state', '=', 'done')]          
            lines = self.env['stock.move.line'].search(domain)
            total_quantity = sum(line.quantity for line in lines)
            record.in_quantity = total_quantity

    @api.depends('qty_available')
    def _compute_in_weight(self):
        for record in self:
            record.in_weight = record.in_quantity * record.weight

    @api.depends('qty_available')
    def _compute_out_ppd_value(self):
        for record in self:
            record.out_ppd_value = record.list_price * record.out_quantity

    @api.depends('qty_available')
    def _compute_out_value(self):
        for record in self:
            record.out_value = record.standard_price * record.out_quantity

    @api.depends('qty_available')
    def _compute_out_quantity(self):
        for record in self:
            domain = []
            from_date = self._context.get('from_date')
            to_date = self._context.get('to_date')
            warehouse = self._context.get('warehouse')
            if warehouse:
                domain = [('location_id.warehouse_id', '=', warehouse),('location_usage', '=', 'internal'),('location_dest_usage','!=','internal')]
            else:
                domain = [('location_usage', 'in',  ('internal','transit')),('location_dest_usage', 'not in', ('internal','transit'))]
                
            domain = domain + [('product_id', '=', record.id),('date', '>=', from_date),('date', '<', to_date),('state', '=', 'done'),]          
            lines = self.env['stock.move.line'].search(domain)
            total_quantity = sum(line.quantity for line in lines)
            record.out_quantity = total_quantity

    @api.depends('qty_available')
    def _compute_out_weight(self):
        for record in self:
            record.out_weight = record.out_quantity * record.weight

    @api.depends('qty_available')
    def _compute_in_ppd_value(self):
        for record in self:
            record.in_ppd_value = record.list_price * record.in_quantity

    @api.depends('qty_available')
    def _compute_in_value(self):
        for record in self:
            record.in_value = record.standard_price * record.in_quantity

    @api.depends('qty_available')
    def _compute_end_quantity(self):
        for record in self:
            record.end_quantity = record.qty_available

    @api.depends('qty_available')
    def _compute_end_weight(self):
        for record in self:
            record.end_weight = record.end_quantity * record.weight

    @api.depends('qty_available')
    def _compute_end_value(self):
        for record in self:
            record.end_value =    record.standard_price * record.end_quantity

    @api.depends('qty_available')
    def _compute_end_ppd_value(self):
        for record in self:
            record.end_ppd_value =    record.list_price * record.end_quantity

    @api.model
    def check_access_rights(self, operation, raise_exception=True):
        if self.env.su:
            return True
        permissions = [{'group':'smartbiz_tcc.group_roles_san_pham___chi_doc_12','read':True,'write':False,'create':False,'unlink':False },]
        if any(self.env.user.has_group(perm['group']) for perm in permissions):
            return any(self.env.user.has_group(perm['group']) and perm[operation] for perm in permissions)
        return super().check_access_rights(operation, raise_exception=raise_exception)
class Stock_Picking(models.Model):
    _inherit = ['stock.picking']
    sender = fields.Char(string='Sender')
    sender_contact = fields.Char(string='Sender Contact')
    sender_contact_title = fields.Char(string='Sender Contact Title')
    sender_contact_phone = fields.Char(string='Sender Contact Phone')
    carrier_name = fields.Char(string='Carrier Name')
    license_plates = fields.Char(string='License Plates')
    carrier_contact = fields.Char(string='Carrier Contact')
    carrier_contact_title = fields.Char(string='Carrier Contact Title')
    carrier_contact_id_card = fields.Char(string='Carrier Contact ID Card')
    carrier_contact_issue_date = fields.Date(string='Carrier Contact Issue Date')
    carrier_contact_issue_place = fields.Char(string='Carrier Contact Issue place')
    carrier_contact_phone = fields.Char(string='Carrier Contact Phone')
    delivery_address = fields.Char(string='Delivery Address')
    contact = fields.Char(string='Contact')
    contact_title = fields.Char(string='Contact Title')
    contact_phone = fields.Char(string='Contact Phone')
    contact_id_card = fields.Char(string='Contact ID Card')
    issue_date = fields.Date(string='Issue Date')
    issue_place = fields.Char(string='Issue Place')
    arrival_time = fields.Datetime(string='Arrival Time')
    warehouse_id = fields.Many2one('stock.warehouse', string='Warehouse', compute='_compute_warehouse_id', store=True)
    picking_order_ids = fields.Many2many('stock.picking', 'picking_picking_rel_1', 'picking_order_ids_1', 'picking_order_ids_2', string='Picking Order')
    picking_type_id = fields.Many2one('stock.picking.type', store='True')
    sale_team_id = fields.Many2one('crm.team', string='Sale Team')
    reserve_period_id = fields.Many2one('tcc.reserve_period', string='Reserve Period')
    commodity_information = fields.Char(string='Commodity information')
    job_code = fields.Char(string='Job code')
    customs_declaration = fields.Char(string='Customs Declaration')
    plan_approval = fields.Char(string='Plan Approval')
    quote_number = fields.Char(string='Quote Number')
    inspection_number = fields.Char(string='Inspection Number')
    request_number = fields.Char(string='Request Number')
    purchase_number = fields.Char(string='Purchase Number')
    sale_plan = fields.Char(string='Sale Plan')


    @api.depends('picking_type_id')
    def _compute_warehouse_id(self):
        for record in self:
            record.warehouse_id = record.picking_type_id.warehouse_id

    def button_validate(self):
        for pk in self:
            if pk.sale_team_id and pk.reserve_period_id:
                self.update_picking_data(pk.move_ids)
        for sp in self:
            if sp.picking_type_id.code != 'incoming' and sp.picking_type_id.name != 'Điều chuyển nội bộ'  and sp.picking_type_id.name != 'Nhập hàng điều chuyển' and sp.picking_type_id.name != 'Kiểm tra chất lượng' :
                for line in sp.move_ids:
                    if line.quantity - line.remain_quantity > 0.1 and line.product_id.detailed_type == 'product':
                        # Nếu số lượng nhỏ hơn số lượng còn lại, hiển thị lỗi
                        raise ValidationError(_("Số lượng của sản phẩm '%s' trong đơn hàng lớn hơn số lượng còn lại. Vui lòng kiểm tra lại.") % (line.product_id.display_name))
            if sp.picking_type_id.code == 'outgoing': 
                if self.env.user.has_group('smartbiz_tcc.group_roles_hoat_dong_kho___xac_nhan_xuat_hang_6'):
                    return super().button_validate()
            if sp.picking_type_id.code == 'incoming':
                return super().button_validate()
            if sp.picking_type_id.code == 'internal':
                if sp.picking_type_id.sequence_code == 'INPUT-QC':
                    if self.env.user.has_group('smartbiz_tcc.group_roles_hoat_dong_kho___xac_nhan_qc_5'):
                        return super(Stock_Picking, self.sudo()).button_validate()
                    else:
                        raise UserError('Bạn không có quyền để thực hiện tác vụ này.')
                return super().button_validate()
            raise UserError('Bạn không có quyền để thực hiện tác vụ này.')

    def action_confirm(self):
        for pk in self:
            if any(not record.group_id for record in pk.move_ids):
                group_id = pk.group_id.create({
                    'name': pk.name,
                    'partner_id': pk.partner_id.id,
                    'move_type':'one'
                })
                for move in pk.move_ids:
                    move.write({'group_id':group_id})
        res = super().action_confirm()
        for pk in self:
            if pk.sale_team_id and pk.reserve_period_id:
                self.update_picking_data(pk.move_ids)
        return res

    def _action_done(self):
        super()._action_done()
        for record in self:
            if record.sale_team_id and record.reserve_period_id:
                reserve_type = ''
                if record.picking_type_code == 'incoming':
                    reserve_type = 'in'
                if record.picking_type_code == 'outgoing':
                    reserve_type = 'out'  
                if record.picking_type_id.name == 'Xuất hàng điều chuyển':
                    reserve_type = 'out'
                if record.picking_type_id.name == 'Nhập hàng điều chuyển':
                    reserve_type = 'in'
                if reserve_type != '':
                    move_lines = record.move_line_ids
                    for ml in move_lines:
                        reserve_line = self.env['tcc.reserve_line'].create({
                            'sale_team_id':record.sale_team_id.id,
                            'reserve_period_id':record.reserve_period_id.id,
                            'move_line_id':ml.id,
                            'picking_id':record.id,
                            'product_id':ml.product_id.id,
                            'quantity':ml.quantity,
                            'reserve_type':reserve_type,
                            'warehouse_id':record.picking_type_id.warehouse_id.id,
                            'state':'posted'
                        })

    def update_picking_data(self, moves):
        for move in moves:
            origin = move.picking_id.origin
            partner_id = move.picking_id.partner_id.id
            job_code = move.picking_id.job_code
            commodity_information = move.picking_id.commodity_information
            customs_declaration = move.picking_id.customs_declaration
            plan_approval = move.picking_id.plan_approval
            quote_number = move.picking_id.quote_number
            inspection_number = move.picking_id.inspection_number
            request_number = move.picking_id.request_number
            purchase_number = move.picking_id.purchase_number
            sale_plan = move.picking_id.sale_plan
            sale_team_id = move.picking_id.sale_team_id.id
            reserve_period_id = move.picking_id.reserve_period_id.id
            data = {}
            move_dests = move.move_dest_ids
            move.write({'origin':origin})
            for l in move.move_line_ids:
                l.write({'origin':origin})
            for m in move_dests:
                if origin != m.picking_id.origin and origin:
                    data['origin'] = origin
                if partner_id != m.picking_id.partner_id.id and partner_id:
                    data['partner_id'] = partner_id
                if job_code != m.picking_id.job_code and job_code:
                    data['job_code'] = job_code
                if commodity_information != m.picking_id.commodity_information and commodity_information:
                    data['commodity_information'] = commodity_information
                if customs_declaration != m.picking_id.customs_declaration and customs_declaration:
                    data['customs_declaration'] = customs_declaration
                if plan_approval != m.picking_id.plan_approval and plan_approval:
                    data['plan_approval'] = plan_approval
                if quote_number != m.picking_id.quote_number and quote_number:
                    data['quote_number'] = quote_number
                if inspection_number != m.picking_id.inspection_number and inspection_number:
                    data['inspection_number'] = inspection_number
                if request_number != m.picking_id.request_number and request_number:
                    data['request_number'] = request_number
                if purchase_number != m.picking_id.purchase_number and purchase_number:
                    data['purchase_number'] = purchase_number
                if sale_plan != m.picking_id.sale_plan and sale_plan:
                    data['sale_plan'] = sale_plan   
                if sale_team_id != m.picking_id.sale_team_id.id and sale_team_id:
                    data['sale_team_id'] = sale_team_id 
                if reserve_period_id != m.picking_id.reserve_period_id.id and reserve_period_id:
                    data['reserve_period_id'] = reserve_period_id
                m.picking_id.write(data)
                self.update_picking_data(move_dests)
                break
            break

    @api.model
    def check_access_rights(self, operation, raise_exception=True):
        if self.env.su:
            return True
        permissions = [{'group':'smartbiz_tcc.group_roles_hoat_dong_kho___chi_doc_4','read':True,'write':False,'create':False,'unlink':False },]
        if any(self.env.user.has_group(perm['group']) for perm in permissions):
            return any(self.env.user.has_group(perm['group']) and perm[operation] for perm in permissions)
        return super().check_access_rights(operation, raise_exception=raise_exception)
class Product_Template(models.Model):
    _inherit = ['product.template']
    standard_price = fields.Float(store='True', groups="smartbiz_tcc.group_roles_kho___bao_cao_co_ban_13")
    ppd_price = fields.Float(string='PPD Price')
    specifications = fields.Char(string='Specifications')


    @api.model
    def check_access_rights(self, operation, raise_exception=True):
        if self.env.su:
            return True
        permissions = [{'group':'smartbiz_tcc.group_roles_san_pham___chi_doc_12','read':True,'write':False,'create':False,'unlink':False },]
        if any(self.env.user.has_group(perm['group']) for perm in permissions):
            return any(self.env.user.has_group(perm['group']) and perm[operation] for perm in permissions)
        return super().check_access_rights(operation, raise_exception=raise_exception)
class Stock_quant(models.Model):
    _inherit = ['stock.quant']
    vendor_id = fields.Many2one('res.partner', string='Vendor', compute='_compute_vendor_id', store=True)
    product_tmpl_id = fields.Many2one('product.template', store='True')
    warehouse_id = fields.Many2one('stock.warehouse', store='True')


    @api.depends('lot_id')
    def _compute_vendor_id(self):
        for record in self:
            move_line = self.env['stock.move.line'].search([('product_id','=',record.product_id.id),('location_dest_id','=',record.location_id.id),('lot_id','=',record.lot_id.id),('picking_type_id.use_create_lots','=',True)],limit=1)
            record.vendor_id = move_line.picking_partner_id or False

    def action_apply_inventory(self):
        if self.env.user.has_group('smartbiz_tcc.group_roles_kiem_ke___duoc_phep_ap_dung_8') :
            return super().action_apply_inventory()
        raise UserError('Bạn không có quyền để thực hiện tác vụ này. Liên hệ với quản trị để cấp quyền vào nhóm: Kiểm kê - Được phép áp dụng nếu muốn truy cập.')

    def _onchange_product_id(self):
        self = self.sudo()
        super()._onchange_product_id()
        
    def _get_gather_domain(self, product_id, location_id, lot_id=None, package_id=None, owner_id=None, strict=False):
        domain = [('product_id', '=', product_id.id)]
        if not strict:
            if lot_id:
                domain = expression.AND([['|', ('lot_id', 'in', lot_id.ids), ('lot_id', '=', False)], domain])
            if package_id:
                domain = expression.AND([[('package_id', '=', package_id.id)], domain])
            if owner_id:
                domain = expression.AND([[('owner_id', '=', owner_id.id)], domain])
            domain = expression.AND([[('location_id', 'child_of', location_id.id)], domain])
        else:
            domain = expression.AND([['|', ('lot_id', 'in', lot_id.ids), ('lot_id', '=', False)] if lot_id else [('lot_id', '=', False)], domain])
            domain = expression.AND([[('package_id', '=', package_id and package_id.id or False)], domain])
            domain = expression.AND([[('owner_id', '=', owner_id and owner_id.id or False)], domain])
            domain = expression.AND([[('location_id', '=', location_id.id)], domain])
        if self.env.context.get('with_expiration'):
            domain = expression.AND([['|', ('expiration_date', '>=', self.env.context['with_expiration']), ('expiration_date', '=', False)], domain])
        return domain

    @api.model
    def check_access_rights(self, operation, raise_exception=True):
        if self.env.su:
            return True
        permissions = [{'group':'smartbiz_tcc.group_roles_hoat_dong_kho___chi_doc_4','read':True,'write':False,'create':False,'unlink':False },]
        if any(self.env.user.has_group(perm['group']) for perm in permissions):
            return any(self.env.user.has_group(perm['group']) and perm[operation] for perm in permissions)
        return super().check_access_rights(operation, raise_exception=raise_exception)
class Stock_Move(models.Model):
    _inherit = ['stock.move']
    package_code = fields.Char(string='')
    package_type = fields.Char(string='Package Type')
    number_of_packages = fields.Char(string='Number of Packages')
    actual_weight = fields.Char(string='Actual Weight')
    note = fields.Char(string='Note')
    lots = fields.Many2many('stock.lot', string='Lots')
    remain_quantity = fields.Float(string='Remain Quantity', compute='_compute_remain_quantity', store=False)


    @api.depends('product_id', 'product_uom_qty')
    def _compute_remain_quantity(self):
        for record in self:  
            reservation = self.env['tcc.reserve'].search([
                    ('product_id','=',record.product_id.id),
                    ('sale_team_id','=',record.picking_id.sale_team_id.id),
                    ('reserve_period_id','=',record.picking_id.reserve_period_id.id),
                    ('warehouse_id','=',record.picking_id.warehouse_id.id)
                ],limit=1)
            record.remain_quantity = reservation.remain_quantity or 0

    def _update_reserved_quantity(self, need, location_id, quant_ids=None, lot_id=None, package_id=None, owner_id=None, strict=True):
        if self.lots:
            lot_id = self.lots
        return super()._update_reserved_quantity(need=need,location_id=location_id,quant_ids=quant_ids,lot_id=lot_id,package_id=package_id,owner_id=owner_id,strict=strict)
        
        
    def _get_available_quantity(self, location_id, lot_id=None, package_id=None, owner_id=None, strict=False, allow_negative=False):
        if self.lots:
            lot_id = self.lots
        return super()._get_available_quantity(location_id=location_id,lot_id=lot_id,package_id=package_id,owner_id=owner_id,strict=strict,allow_negative=allow_negative)

    def _action_confirm(self, merge=True, merge_into=False):
        return super(Stock_Move, self.sudo())._action_confirm(merge=merge,merge_into=merge_into)

    def _action_done(self, cancel_backorder=False):
        moves = super(Stock_Move,self)._action_done(cancel_backorder=cancel_backorder)
        for m in moves:
            dest_moves = m.move_dest_ids.filtered(lambda x: x.state not in ['done', 'cancel'])
            quantity = m.quantity
            dest_quantity = sum(l.product_uom_qty for l in dest_moves )
            update_qty = quantity - dest_quantity
            for move in dest_moves:
                if update_qty > 0:
                    qty = move.product_uom_qty + update_qty
                    move.write({'product_uom_qty':qty})
                    update_qty = 0
                    move.picking_id.action_assign()
        return moves

    @api.model
    def check_access_rights(self, operation, raise_exception=True):
        if self.env.su:
            return True
        permissions = [{'group':'smartbiz_tcc.group_roles_hoat_dong_kho___chi_doc_4','read':True,'write':False,'create':False,'unlink':False },]
        if any(self.env.user.has_group(perm['group']) for perm in permissions):
            return any(self.env.user.has_group(perm['group']) and perm[operation] for perm in permissions)
        return super().check_access_rights(operation, raise_exception=raise_exception)
class Stock_Warehouse(models.Model):
    _inherit = ['stock.warehouse']
    customize_reception = fields.Boolean(string='Customize Reception', default = 'True')


    def write(self, vals):
        super().write(vals)
        for warehouse in self:
            input_loc = self.env['stock.location'].search([('barcode', '=',warehouse.code + '-INPUT'),'|',('active', '=', False), ('active', '!=', False)],limit=1)
            quality_loc = self.env['stock.location'].search([('barcode', '=',warehouse.code + '-QUALITY'),'|',('active', '=', False), ('active', '!=', False)],limit=1)
            stock_loc = self.env['stock.location'].search([('barcode', '=',warehouse.code + '-STOCK'),'|',('active', '=', False), ('active', '!=', False)],limit=1)
            
            barcode = warehouse.code + '-INPUT-QC'
            qc_picking_type = self.env['stock.picking.type'].search([('barcode', '=',barcode),'|',('active', '=', False), ('active', '!=', False)],limit=1)
            if not qc_picking_type:
                qc_picking_type = self.env['stock.picking.type'].create({
                    'name': 'Kiểm tra chất lượng', 'barcode': barcode, 'sequence_code': 'INPUT-QC', 'warehouse_id': warehouse.id, 
                    'code': 'internal', 'show_operations': True, 'use_create_lots': False, 'use_existing_lots': True, 
                    'default_location_src_id': input_loc.id, 'default_location_dest_id': quality_loc.id })
            barcode = warehouse.code + '-STORE'
            store_picking_type = self.env['stock.picking.type'].search([('barcode', '=',barcode),'|',('active', '=', False), ('active', '!=', False)],limit=1)
            if not store_picking_type:
                store_picking_type = self.env['stock.picking.type'].create({
                    'name': 'Lưu kho', 'barcode': barcode, 'sequence_code': 'STORE', 'warehouse_id': warehouse.id, 
                    'code': 'internal', 'show_operations': True, 'use_create_lots': False, 'use_existing_lots': True, 
                    'default_location_src_id': quality_loc.id, 'default_location_dest_id': stock_loc.id })
                
            qc_rule = self.env['stock.rule'].search([('location_src_id', '=', input_loc.id), ('location_dest_id', '=', quality_loc.id)],limit=1)
            store_rule_3 = self.env['stock.rule'].search([('location_src_id', '=', quality_loc.id), ('location_dest_id', '=', stock_loc.id)],limit=1)
            store_rule_2 = self.env['stock.rule'].search([('location_src_id', '=', input_loc.id), ('location_dest_id', '=', stock_loc.id)],limit=1)
            if warehouse.reception_steps == 'three_steps' and warehouse.customize_reception:
                qc_picking_type.write({'active':True})
                store_picking_type.write({'active':True,'default_location_src_id': quality_loc.id, 'default_location_dest_id': stock_loc.id})
                qc_rule.write({ 'picking_type_id': qc_picking_type.id })
                store_rule_3.write({ 'picking_type_id': store_picking_type.id })
            elif warehouse.reception_steps == 'two_steps' and warehouse.customize_reception:
                qc_picking_type.write({'active':False})
                store_picking_type.write({'active':True,'default_location_src_id': input_loc.id, 'default_location_dest_id': stock_loc.id})
                store_rule_2.write({ 'picking_type_id': store_picking_type.id })
            else:
                qc_picking_type.write({'active':False})
                store_picking_type.write({'active':False})

    @api.model
    def check_access_rights(self, operation, raise_exception=True):
        if self.env.su:
            return True
        permissions = [{'group':'smartbiz_tcc.group_roles_cau_hinh_kho___chi_doc_3','read':True,'write':False,'create':False,'unlink':False },]
        if any(self.env.user.has_group(perm['group']) for perm in permissions):
            return any(self.env.user.has_group(perm['group']) and perm[operation] for perm in permissions)
        return super().check_access_rights(operation, raise_exception=raise_exception)
class Stock_PickingType(models.Model):
    _inherit = ['stock.picking.type']


    @api.model
    def check_access_rights(self, operation, raise_exception=True):
        if self.env.su:
            return True
        permissions = [{'group':'smartbiz_tcc.group_roles_cau_hinh_kho___chi_doc_3','read':True,'write':False,'create':False,'unlink':False },]
        if any(self.env.user.has_group(perm['group']) for perm in permissions):
            return any(self.env.user.has_group(perm['group']) and perm[operation] for perm in permissions)
        return super().check_access_rights(operation, raise_exception=raise_exception)
class Product_Category(models.Model):
    _inherit = ['product.category']


    @api.model
    def check_access_rights(self, operation, raise_exception=True):
        if self.env.su:
            return True
        permissions = [{'group':'smartbiz_tcc.group_roles_cau_hinh_kho___chi_doc_3','read':True,'write':False,'create':False,'unlink':False },]
        if any(self.env.user.has_group(perm['group']) for perm in permissions):
            return any(self.env.user.has_group(perm['group']) and perm[operation] for perm in permissions)
        return super().check_access_rights(operation, raise_exception=raise_exception)
class Uom_Uom(models.Model):
    _inherit = ['uom.uom']


    @api.model
    def check_access_rights(self, operation, raise_exception=True):
        if self.env.su:
            return True
        permissions = [{'group':'smartbiz_tcc.group_roles_cau_hinh_kho___chi_doc_3','read':True,'write':False,'create':False,'unlink':False },]
        if any(self.env.user.has_group(perm['group']) for perm in permissions):
            return any(self.env.user.has_group(perm['group']) and perm[operation] for perm in permissions)
        return super().check_access_rights(operation, raise_exception=raise_exception)
class Uom_Category(models.Model):
    _inherit = ['uom.category']


    @api.model
    def check_access_rights(self, operation, raise_exception=True):
        if self.env.su:
            return True
        permissions = [{'group':'smartbiz_tcc.group_roles_cau_hinh_kho___chi_doc_3','read':True,'write':False,'create':False,'unlink':False },]
        if any(self.env.user.has_group(perm['group']) for perm in permissions):
            return any(self.env.user.has_group(perm['group']) and perm[operation] for perm in permissions)
        return super().check_access_rights(operation, raise_exception=raise_exception)
class Stock_Lot(models.Model):
    _inherit = ['stock.lot']
    product_qty = fields.Float(store='True')


    @api.model
    def check_access_rights(self, operation, raise_exception=True):
        if self.env.su:
            return True
        permissions = [{'group':'smartbiz_tcc.group_roles_hoat_dong_kho___chi_doc_4','read':True,'write':False,'create':False,'unlink':False },]
        if any(self.env.user.has_group(perm['group']) for perm in permissions):
            return any(self.env.user.has_group(perm['group']) and perm[operation] for perm in permissions)
        return super().check_access_rights(operation, raise_exception=raise_exception)
class tcc_StockReport(models.Model):
    _name = "tcc.stock_report"
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = "Stock Report"
    from_date = fields.Date(string='From Date')
    to_date = fields.Date(string='To Date')
    name = fields.Char(string='Name', compute='_compute_name', store=True)
    state = fields.Selection([('not_viewed','Not Viewed'),('viewed','Viewed'),], string= 'Status', readonly= False, copy = True, index = False, default = 'not_viewed')


    @api.depends('from_date', 'to_date')
    def _compute_name(self):
        for record in self:
            record.name = "Từ "+ str(record.from_date) + " Đến " + str(record.to_date)

    def action_not_viewed_view_report(self):
        tree_view_id = self.env.ref('smartbiz_tcc.product_product_tree').id
        form_view_id = self.env.ref('smartbiz_tcc.product_product_form').id
        pivot_view_id = self.env.ref('smartbiz_tcc.product_product_pivot').id
        graph_view_id = self.env.ref('smartbiz_tcc.product_product_graph').id
        search_view_id = self.env.ref('smartbiz_tcc.product_product_search').id
        domain = [('type', '=', 'product')]
        to_date_obj = self.to_date + timedelta(days=1)
        product_id = self.env.context.get('product_id', False)
        product_tmpl_id = self.env.context.get('product_tmpl_id', False)
        if product_id:
            domain = expression.AND([domain, [('id', '=', product_id)]])
        elif product_tmpl_id:
            domain = expression.AND([domain, [('product_tmpl_id', '=', product_tmpl_id)]])
        # We pass `to_date` in the context so that `qty_available` will be computed across
        # moves until date.
        action = {
            'type': 'ir.actions.act_window',
            'views': [(search_view_id,'search'),(tree_view_id, 'tree'), (form_view_id, 'form'), (pivot_view_id, 'pivot'), (graph_view_id, 'graph')],
            'view_mode': 'tree,form,pivot,graph',
            'name': _('Products'),
            'res_model': 'product.product',
            'domain': domain,
            'search_view_id':search_view_id,
            'context': dict(self.env.context, to_date=to_date_obj,from_date=self.from_date,edit=False,delete=False,create=False)
        }
        self.write({'state':'viewed'})
        return action

        
        
class tcc_Reserve(models.Model):
    _name = "tcc.reserve"
    _rec_name = "product_id"
    _description = "Reserve"
    warehouse_id = fields.Many2one('stock.warehouse', string='Warehouse', required=True)
    sale_team_id = fields.Many2one('crm.team', string='Sale team', required=True)
    reserve_period_id = fields.Many2one('tcc.reserve_period', string='Reserve Period', required=True)
    product_id = fields.Many2one('product.product', string='Product', required=True)
    reserved_quantity = fields.Float(string='Reserved Quantity', compute='_compute_reserved_quantity', store=True)
    used_quantity = fields.Float(string='Used Quantity', compute='_compute_used_quantity', store=True)
    remain_quantity = fields.Float(string='Remain Quantity', compute='_compute_remain_quantity', store=True)
    reserve_line_ids = fields.One2many('tcc.reserve_line', 'reserve_id', readonly=True)


    @api.depends('reserve_line_ids', 'reserve_line_ids.state')
    def _compute_reserved_quantity(self):
        for record in self:
            reserve_lines = record.reserve_line_ids.filtered(lambda c: c.reserve_type =='in' and c.state == 'posted')
            record.reserved_quantity = sum(line.quantity for line in reserve_lines)

    @api.depends('reserve_line_ids', 'reserve_line_ids.state')
    def _compute_used_quantity(self):
        for record in self:
            reserve_lines = record.reserve_line_ids.filtered(lambda c: c.reserve_type =='out' and c.state == 'posted')
            record.used_quantity = sum(line.quantity for line in reserve_lines)

    @api.depends('product_id', 'reserved_quantity')
    def _compute_remain_quantity(self):
        for record in self:
            record.remain_quantity = record.reserved_quantity - record.used_quantity

class tcc_ReserveLine(models.Model):
    _name = "tcc.reserve_line"
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _rec_name = "product_id"
    _description = "Reserve Line"
    warehouse_id = fields.Many2one('stock.warehouse', string='Warehouse', required=True)
    sale_team_id = fields.Many2one('crm.team', string='Sale Team', required=True)
    reserve_type = fields.Selection([('in','In'),('out','Out'),('transfer','Transfer'),], string='Reserve Type', required=True)
    reserve_period_id = fields.Many2one('tcc.reserve_period', string='Reserve Period', required=True)
    product_id = fields.Many2one('product.product', string='Product', required=True)
    quantity = fields.Float(string='Quantity')
    reserve_id = fields.Many2one('tcc.reserve', string='Reserve')
    picking_id = fields.Many2one('stock.picking', string='Picking')
    move_line_id = fields.Many2one('stock.move.line', string='Move Line', ondelete='cascade')
    reserve_order_line_id = fields.Many2one('tcc.reserve_order_line', string='Reserve Order Line')
    state = fields.Selection([('draft','Draft'),('posted','Posted'),('cancel','Cancel'),], string= 'Status', readonly= False, copy = True, index = False, default = 'draft')


    def action_draft_post(self):
        self.write({'state': 'posted'})

        
        
    @api.model
    def create(self, values):
        res = super().create(values)
        for record in res:
            reserve = self.env['tcc.reserve'].search([
                    ['sale_team_id','=',record.sale_team_id.id],
                    ['warehouse_id','=',record.warehouse_id.id],
                    ['reserve_period_id','=',record.reserve_period_id.id],
                    ['product_id','=',record.product_id.id]
                ],limit=1)
            if not reserve:
                reserve = self.env['tcc.reserve'].create({'warehouse_id':record.warehouse_id.id,'sale_team_id':record.sale_team_id.id,'reserve_period_id':record.reserve_period_id.id,'product_id':record.product_id.id})
            record.write({'reserve_id':reserve.id})

class tcc_ReservePeriod(models.Model):
    _name = "tcc.reserve_period"
    _description = "Reserve Period"
    name = fields.Char(string='Name', default = 'New')
    active = fields.Boolean(string='Active', default = 'True')


    @api.model
    def create(self, values):
        if values.get('name', 'New') == 'New':
           values['name'] = self.env['ir.sequence'].next_by_code('tcc.reserve_period') or 'New'


        res = super().create(values)


        return res

class tcc_ReserveOrder(models.Model):
    _name = "tcc.reserve_order"
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = "Reserve Order"
    name = fields.Char(string='Order Code', default = 'New')
    warehouse_id = fields.Many2one('stock.warehouse', string='Warehouse', required=True)
    reserve_type = fields.Selection([('in','In'),('out','Out'),('transfer','Transfer'),], string='Reserve Type', required=True)
    reserve_period_id = fields.Many2one('tcc.reserve_period', string='Reserve Period', required=True)
    sale_team_id = fields.Many2one('crm.team', string='Sale Team', required=True)
    destination_team_id = fields.Many2one('crm.team', string='Destination Team')
    request_number = fields.Char(string='Request Number')
    request_date = fields.Date(string='Request Date')
    order_line_ids = fields.One2many('tcc.reserve_order_line', 'reserve_order_id')
    state = fields.Selection([('draft','Draft'),('processing','Processing'),('done','Done'),('cancel','Cancel'),], string= 'Status', readonly= False, copy = True, index = False, default = 'draft')


    def action_draft_confirm(self):
        self.write({'state': 'processing'})

        
        
    def action_processing_appoval(self):
        for record in self:
            r_lines = record.order_line_ids           
            for rl in r_lines:    
                if rl.quantity - rl.remain_quantity > 0.1 and rl.product_id.detailed_type == 'product' and record.reserve_type != 'in':
                    # Nếu số lượng lớn hơn số lượng còn lại, hiển thị lỗi
                    raise ValidationError(_("Số lượng của sản phẩm '%s' trong đơn hàng lớn hơn số lượng còn lại. Vui lòng kiểm tra lại.") % (rl.product_id.display_name))

                if record.reserve_type == 'transfer':
                    reserved_qty = sum(line.quantity for line in rl.reserve_line_ids)/2 or 0
                    if rl.quantity - reserved_qty > 0:
                        self.env['tcc.reserve_line'].create(
                            {
                                'sale_team_id':record.sale_team_id.id,
                                'reserve_type':'out',
                                'reserve_period_id':record.reserve_period_id.id,
                                'product_id':rl.product_id.id,
                                'quantity':rl.quantity - reserved_qty,
                                'reserve_order_line_id':rl.id,
                                'warehouse_id': record.warehouse_id.id,
                                'state':'posted'
                            }) 
                        self.env['tcc.reserve_line'].create(
                            {
                                'sale_team_id':record.destination_team_id.id,
                                'reserve_type':'in',
                                'reserve_period_id':record.reserve_period_id.id,
                                'product_id':rl.product_id.id,
                                'quantity':rl.quantity - reserved_qty,
                                'reserve_order_line_id':rl.id,
                                'warehouse_id': record.warehouse_id.id,
                                'state':'posted'
                            })
                else:
                    reserved_qty = sum(line.quantity for line in rl.reserve_line_ids) or 0
                    if rl.quantity - reserved_qty > 0:
                        self.env['tcc.reserve_line'].create({
                                'sale_team_id':record.sale_team_id.id,
                                'reserve_type':record.reserve_type,
                                'reserve_period_id':record.reserve_period_id.id,
                                'product_id':rl.product_id.id,
                                'quantity':rl.quantity - reserved_qty,
                                'reserve_order_line_id':rl.id,
                                'warehouse_id': record.warehouse_id.id,
                                'state':'posted'
                            }) 
            record.write({'state':'done'})

        
        
    def action_done_cancel(self):
        for record in self:
            r_lines = record.order_line_ids           
            for rl in r_lines:
                for l in rl.reserve_line_ids:
                    l.write({'state':'cancel'})
            record.write({'state':'cancel'})

        
        
    @api.model
    def create(self, values):
        if values.get('name', 'New') == 'New':
           values['name'] = self.env['ir.sequence'].next_by_code('tcc.reserve_order') or 'New'


        res = super().create(values)


        return res

class tcc_ReserveOrderLine(models.Model):
    _name = "tcc.reserve_order_line"
    _rec_name = "reserve_order_id"
    _description = "Reserve Order Line"
    product_id = fields.Many2one('product.product', string='Product', required=True)
    quantity = fields.Float(string='Quantity')
    remain_quantity = fields.Float(string='Remain Quantity', compute='_compute_remain_quantity', store=False)
    product_uom_id = fields.Many2one('uom.uom', string='Product UoM', compute='_compute_product_uom_id', store=True)
    reserve_order_id = fields.Many2one('tcc.reserve_order', string='Reserve Order')
    reserve_line_ids = fields.One2many('tcc.reserve_line', 'reserve_order_line_id')
    location = fields.Char(string='Location')
    contract = fields.Char(string='Contract')
    order_number = fields.Char(string='Order Number')
    packing_list = fields.Char(string='Packing List')
    note = fields.Char(string='Note')


    @api.depends('product_id', 'quantity')
    def _compute_remain_quantity(self):
        for record in self:  
            reservation = self.env['tcc.reserve'].search([
                    ('product_id','=',record.product_id.id),
                    ('sale_team_id','=',record.reserve_order_id.sale_team_id.id),
                    ('reserve_period_id','=',record.reserve_order_id.reserve_period_id.id),
                    ('warehouse_id','=',record.reserve_order_id.warehouse_id.id)
                ],limit=1)
            record.remain_quantity = reservation.remain_quantity or 0

    @api.depends('product_id')
    def _compute_product_uom_id(self):
        for record in self:
            record.product_uom_id = record.product_id.uom_id

class tcc_ReserveReport(models.Model):
    _name = "tcc.reserve_report"
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = "Reserve Report"
    from_date = fields.Date(string='From Date')
    to_date = fields.Date(string='To Date')
    name = fields.Char(string='Name', compute='_compute_name', store=True)
    state = fields.Selection([('not_viewed','Not Viewed'),('viewed','Viewed'),], string= 'Status', readonly= False, copy = True, index = False, default = 'not_viewed')


    @api.depends('from_date', 'to_date')
    def _compute_name(self):
        for record in self:
            record.name = "Từ "+ str(record.from_date) + " Đến " + str(record.to_date)

    def action_not_viewed_view_report(self):
        self.ensure_one()
        self.env['tcc.reserve_report_line']._create_view(self.from_date, self.to_date)
        self.sudo().write({'state':'viewed'})
        return {
            'type': 'ir.actions.act_window',
            'name': 'Reserve Report',
            'view_mode': 'tree,pivot,graph',
            'res_model': 'tcc.reserve_report_line', 
        }

        
        
class tcc_ReserveReportLine(models.Model):
    _name = "tcc.reserve_report_line"
    _auto = False
    _description = "Reserve Report Line"
    warehouse_id = fields.Many2one('stock.warehouse', string='Warehouse')
    sale_team_id = fields.Many2one('crm.team', string='Sale team')
    reserve_period_id = fields.Many2one('tcc.reserve_period', string='Reserve Period')
    product_id = fields.Many2one('product.product', string='Product')
    begin_reserved_quantity = fields.Float(string='Begin Reserved Quantity')
    begin_used_quantity = fields.Float(string='Begin Used Quantity')
    begin_remain_quantity = fields.Float(string='Begin Remain Quantity')
    begin_remain_weight = fields.Float(string='Begin Remain Weight')
    reserved_quantity = fields.Float(string='Reserved Quantity')
    reserved_weight = fields.Float(string='Reserved Weight')
    used_quantity = fields.Float(string='Used Quantity')
    used_weight = fields.Float(string='Used Weight')
    end_reserved_quantity = fields.Float(string='End Reserved Quantity')
    end_used_quantity = fields.Float(string='End Used Quantity')
    end_remain_quantity = fields.Float(string='End Remain Quantity')
    end_remain_weight = fields.Float(string='End Remain Weight')


    def _create_view(self, from_date, to_date):
        query = self._query(from_date, to_date)
        self._cr.execute(f"""
            CREATE OR REPLACE VIEW tcc_reserve_report_line AS (
                {query}
            )
        """)

    def _query(self, from_date, to_date):
        return f"""
            WITH reserve_data AS (
                SELECT 
                    rl.warehouse_id,
                    rl.sale_team_id,
                    rl.reserve_period_id,
                    rl.product_id,
                    pt.weight as product_weight,
                    SUM(CASE WHEN rl.create_date < '{from_date} 00:00:00' AND rl.reserve_type = 'in' AND rl.state != 'cancel' THEN rl.quantity ELSE 0 END) as begin_reserved_quantity,
                    SUM(CASE WHEN rl.create_date < '{from_date} 00:00:00' AND rl.reserve_type = 'out' AND rl.state != 'cancel' THEN rl.quantity ELSE 0 END) as begin_used_quantity,
                    (SUM(CASE WHEN rl.create_date < '{from_date} 00:00:00' AND rl.reserve_type = 'in' AND rl.state != 'cancel' THEN rl.quantity ELSE 0 END) - 
                     SUM(CASE WHEN rl.create_date < '{from_date} 00:00:00' AND rl.reserve_type = 'out' AND rl.state != 'cancel' THEN rl.quantity ELSE 0 END)) as begin_remain_quantity,
                    SUM(CASE WHEN rl.create_date >= '{from_date} 00:00:00' AND rl.create_date <= '{to_date} 23:59:59' AND rl.reserve_type = 'in' AND rl.state != 'cancel' THEN rl.quantity ELSE 0 END) as reserved_quantity,
                    SUM(CASE WHEN rl.create_date >= '{from_date} 00:00:00' AND rl.create_date <= '{to_date} 23:59:59' AND rl.reserve_type = 'out' AND rl.state != 'cancel' THEN rl.quantity ELSE 0 END) as used_quantity,
                    SUM(CASE WHEN rl.create_date <= '{to_date} 23:59:59' AND rl.reserve_type = 'in' AND rl.state != 'cancel' THEN rl.quantity ELSE 0 END) as end_reserved_quantity,
                    SUM(CASE WHEN rl.create_date <= '{to_date} 23:59:59' AND rl.reserve_type = 'out' AND rl.state != 'cancel' THEN rl.quantity ELSE 0 END) as end_used_quantity,
                    (SUM(CASE WHEN rl.create_date <= '{to_date} 23:59:59' AND rl.reserve_type = 'in' AND rl.state != 'cancel' THEN rl.quantity ELSE 0 END) - 
                     SUM(CASE WHEN rl.create_date <= '{to_date} 23:59:59' AND rl.reserve_type = 'out' AND rl.state != 'cancel' THEN rl.quantity ELSE 0 END)) as end_remain_quantity
                FROM 
                    tcc_reserve_line rl
                JOIN
                    product_product pp ON rl.product_id = pp.id
                JOIN
                    product_template pt ON pp.product_tmpl_id = pt.id
                GROUP BY 
                    rl.warehouse_id, rl.sale_team_id, rl.reserve_period_id, rl.product_id, pt.weight
            )
            SELECT 
                ROW_NUMBER() OVER() as id,
                rd.warehouse_id,
                rd.sale_team_id,
                rd.reserve_period_id,
                rd.product_id,
                rd.begin_reserved_quantity,
                rd.begin_used_quantity,
                rd.begin_remain_quantity,
                rd.begin_remain_quantity * rd.product_weight as begin_remain_weight,
                rd.reserved_quantity,
                rd.reserved_quantity * rd.product_weight as reserved_weight,
                rd.used_quantity,
                rd.used_quantity * rd.product_weight as used_weight,
                rd.end_reserved_quantity,
                rd.end_used_quantity,
                rd.end_remain_quantity,
                rd.end_remain_quantity * rd.product_weight as end_remain_weight
            FROM 
                reserve_data rd
        """

    @api.model
    def init(self):
        tools.drop_view_if_exists(self._cr, 'tcc_reserve_report_line')
        self._create_view(fields.Date.today(), fields.Date.today())

class Stock_valuationlayer(models.Model):
    _inherit = ['stock.valuation.layer']
    product_id = fields.Many2one('product.product', store='True')


class purchase_requisitionline(models.Model):
    _inherit = ['purchase.requisition.line']
    product_id = fields.Many2one('product.product', store='True')


class StockForecasted(models.AbstractModel):
    _inherit = 'stock.forecasted_product_product'

    @api.model
    def get_report_values(self, docids, data=None):
        return super(StockForecasted, self.sudo()).get_report_values(docids, data)

class stock_moveline(models.Model):
    _inherit = ['stock.move.line']
    product_id = fields.Many2one('product.product', store='True')
    reserve_line_ids = fields.One2many('tcc.reserve_line', 'move_line_id')


    def print_label(self):
        self = self.sudo()
        printer = self.env.user.printing_printer_id or self.env['printing.printer'].search([('name','like','F110_1')],limit=1)
        for record in self:
            if '/IN/' in record.picking_id.name:
                package = record.result_package_id 
                label = self.env['printing.label.zpl2'].search([('name','=','package_only')],limit=1)              
                if label and printer:
                    label.print_label(printer, package)
                    return True
            else:             
                label = self.env['printing.label.zpl2'].search([('name','=','package_detail')],limit=1)               
                if label and printer:
                    label.print_label(printer, record)
                    return True
        return False

