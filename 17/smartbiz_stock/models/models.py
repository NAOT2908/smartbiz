# -*- coding: utf-8 -*-

from odoo.osv import expression
from odoo import models, fields, api, exceptions,_, tools
import os
import base64,pytz,logging,unidecode
from datetime import datetime, timedelta
import random
from odoo.exceptions import UserError, ValidationError
from odoo.tools import config, float_compare
_logger = logging.getLogger(__name__)
from io import BytesIO
import xlsxwriter
from openpyxl import load_workbook

class Product_Product(models.Model):
    _inherit = ['product.product']
    default_code = fields.Char(store='True', tracking=True)


    @api.model
    def create(self, vals):
        #Kiểm tra default_code
        if 'default_code' in vals and vals['default_code']:
            existed = self.search([
                ('default_code', '=', vals['default_code'])
            ], limit=1)
            if existed:
                raise ValidationError(
                    "Sản phẩm với mã {} đã tồn tại!".format(vals['default_code'])
                )
        return super().create(vals)

    @api.model
    def check_access_rights(self, operation, raise_exception=True):
        if self.env.su:
            return True
        permissions = [{'group':'smartbiz_stock.group_roles_inventory___product_readonly_4','read':True,'write':False,'create':False,'unlink':False },]
        if any(self.env.user.has_group(perm['group']) for perm in permissions):
            return any(self.env.user.has_group(perm['group']) and perm[operation] for perm in permissions)
        return super().check_access_rights(operation, raise_exception=raise_exception)

class Product_Template(models.Model):
    _inherit = ['product.template']
    allow_negative_stock = fields.Boolean(string='Allow Negative Stock')
    default_code = fields.Char(store='True', tracking=True)


    @api.model
    def create(self, vals):
        #Kiểm tra default_code
        if 'default_code' in vals and vals['default_code']:
            existed = self.search([
                ('default_code', '=', vals['default_code'])
            ], limit=1)
            if existed:
                raise ValidationError(
                    "Sản phẩm với mã {} đã tồn tại!".format(vals['default_code'])
                )
        return super().create(vals)

    @api.model
    def check_access_rights(self, operation, raise_exception=True):
        if self.env.su:
            return True
        permissions = [{'group':'smartbiz_stock.group_roles_inventory___product_readonly_4','read':True,'write':False,'create':False,'unlink':False },]
        if any(self.env.user.has_group(perm['group']) for perm in permissions):
            return any(self.env.user.has_group(perm['group']) and perm[operation] for perm in permissions)
        return super().check_access_rights(operation, raise_exception=raise_exception)

class Stock_Quant(models.Model):
    _inherit = ['stock.quant']
    warehouse_id = fields.Many2one('stock.warehouse', store='True')


    def action_apply_inventory(self):
        if self.env.user.has_group('smartbiz_stock.group_roles_inventory_adjustment___allow_apply_3') :
            return super().action_apply_inventory()
        raise UserError('Bạn không có quyền để thực hiện tác vụ này. Liên hệ với quản trị để cấp quyền vào nhóm: Kiểm kê - Được phép áp dụng nếu muốn truy cập.')

    def _onchange_product_id(self):
        self = self.sudo()
        super()._onchange_product_id()
        
    def _get_gather_domain_(self, product_id, location_id, lot_id=None, package_id=None, owner_id=None, strict=False):
        domain = [('product_id', '=', product_id.id)]
        if not strict:
            if lot_id:
                domain = expression.AND([['|', ('lot_id', '=', lot_id.ids), ('lot_id', '=', False)], domain])
            if package_id:
                domain = expression.AND([[('package_id', '=', package_id.id)], domain])
            if owner_id:
                domain = expression.AND([[('owner_id', '=', owner_id.id)], domain])
            domain = expression.AND([[('location_id', 'child_of', location_id.id)], domain])
        else:
            domain = expression.AND([['|', ('lot_id', '=', lot_id.ids), ('lot_id', '=', False)] if lot_id else [('lot_id', '=', False)], domain])
            domain = expression.AND([[('package_id', '=', package_id and package_id.id or False)], domain])
            domain = expression.AND([[('owner_id', '=', owner_id and owner_id.id or False)], domain])
            domain = expression.AND([[('location_id', '=', location_id.id)], domain])
        if self.env.context.get('with_expiration'):
            domain = expression.AND([['|', ('expiration_date', '>=', self.env.context['with_expiration']), ('expiration_date', '=', False)], domain])
        return domain

    @api.constrains("product_id", "quantity")
    def check_negative_qty(self):
        p = self.env["decimal.precision"].precision_get("Product Unit of Measure")
        check_negative_qty = (
            config["test_enable"] and self.env.context.get("test_stock_no_negative")
        ) or not config["test_enable"]
        if not check_negative_qty:
            return

        for quant in self:
            disallowed_by_product = (
                not quant.product_id.allow_negative_stock
                and not quant.product_id.categ_id.allow_negative_stock
            )
            disallowed_by_location = not quant.location_id.allow_negative_stock
            if (
                float_compare(quant.quantity, 0, precision_digits=p) == -1
                and quant.product_id.type == "product"
                and quant.location_id.usage in ["internal", "transit"]
                and disallowed_by_product
                and disallowed_by_location
            ):
                msg_add = ""
                if quant.lot_id:
                    msg_add = _(" lot {}").format(quant.lot_id.name_get()[0][1])
                raise ValidationError(
                    _(
                        "You cannot validate this stock operation because the "
                        "stock level of the product '{name}'{name_lot} would "
                        "become negative "
                        "({q_quantity}) on the stock location '{complete_name}' "
                        "and negative stock is "
                        "not allowed for this product and/or location."
                    ).format(
                        name=quant.product_id.display_name,
                        name_lot=msg_add,
                        q_quantity=quant.quantity,
                        complete_name=quant.location_id.complete_name,
                    )
                )

    @api.model
    def check_access_rights(self, operation, raise_exception=True):
        if self.env.su:
            return True
        permissions = [{'group':'smartbiz_stock.group_roles_inventory___move_readonly_6','read':True,'write':False,'create':False,'unlink':False },]
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
        permissions = [{'group':'smartbiz_stock.group_roles_inventory___move_readonly_6','read':True,'write':False,'create':False,'unlink':False },]
        if any(self.env.user.has_group(perm['group']) for perm in permissions):
            return any(self.env.user.has_group(perm['group']) and perm[operation] for perm in permissions)
        return super().check_access_rights(operation, raise_exception=raise_exception)

class Stock_Move(models.Model):
    _inherit = ['stock.move']
    lots = fields.Many2many('stock.lot', string='Lots')
    product_id = fields.Many2one('product.product', store='True')
    transfer_request_line_id = fields.Many2one('smartbiz_stock.transfer_request_line', string='Transfer Request Line')


    def _update_reserved_quantity(self, need, location_id, quant_ids=None, lot_id=None, package_id=None, owner_id=None, strict=True):
        if self.lots:
            lot_id = self.lots
        return super()._update_reserved_quantity(need=need,location_id=location_id,quant_ids=quant_ids,lot_id=lot_id,package_id=package_id,owner_id=owner_id,strict=strict)
        
        
    def _get_available_quantity(self, location_id, lot_id=None, package_id=None, owner_id=None, strict=False, allow_negative=False):
        if self.lots:
            lot_id = self.lots
        return super()._get_available_quantity(location_id=location_id,lot_id=lot_id,package_id=package_id,owner_id=owner_id,strict=strict,allow_negative=allow_negative)

    @api.model
    def check_access_rights(self, operation, raise_exception=True):
        if self.env.su:
            return True
        permissions = [{'group':'smartbiz_stock.group_roles_inventory___move_readonly_6','read':True,'write':False,'create':False,'unlink':False },]
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
        permissions = [{'group':'smartbiz_stock.group_roles_inventory___configuaration_readonly_5','read':True,'write':False,'create':False,'unlink':False },]
        if any(self.env.user.has_group(perm['group']) for perm in permissions):
            return any(self.env.user.has_group(perm['group']) and perm[operation] for perm in permissions)
        return super().check_access_rights(operation, raise_exception=raise_exception)

class Stock_PickingType(models.Model):
    _inherit = ['stock.picking.type']


    @api.model
    def check_access_rights(self, operation, raise_exception=True):
        if self.env.su:
            return True
        permissions = [{'group':'smartbiz_stock.group_roles_inventory___configuaration_readonly_5','read':True,'write':False,'create':False,'unlink':False },]
        if any(self.env.user.has_group(perm['group']) for perm in permissions):
            return any(self.env.user.has_group(perm['group']) and perm[operation] for perm in permissions)
        return super().check_access_rights(operation, raise_exception=raise_exception)

class Product_Category(models.Model):
    _inherit = ['product.category']
    allow_negative_stock = fields.Boolean(string='Allow Negative Stock')


    @api.model
    def check_access_rights(self, operation, raise_exception=True):
        if self.env.su:
            return True
        permissions = [{'group':'smartbiz_stock.group_roles_inventory___configuaration_readonly_5','read':True,'write':False,'create':False,'unlink':False },]
        if any(self.env.user.has_group(perm['group']) for perm in permissions):
            return any(self.env.user.has_group(perm['group']) and perm[operation] for perm in permissions)
        return super().check_access_rights(operation, raise_exception=raise_exception)

class Uom_Uom(models.Model):
    _inherit = ['uom.uom']


    @api.model
    def check_access_rights(self, operation, raise_exception=True):
        if self.env.su:
            return True
        permissions = [{'group':'smartbiz_stock.group_roles_inventory___configuaration_readonly_5','read':True,'write':False,'create':False,'unlink':False },]
        if any(self.env.user.has_group(perm['group']) for perm in permissions):
            return any(self.env.user.has_group(perm['group']) and perm[operation] for perm in permissions)
        return super().check_access_rights(operation, raise_exception=raise_exception)

class Uom_Category(models.Model):
    _inherit = ['uom.category']


    @api.model
    def check_access_rights(self, operation, raise_exception=True):
        if self.env.su:
            return True
        permissions = [{'group':'smartbiz_stock.group_roles_inventory___configuaration_readonly_5','read':True,'write':False,'create':False,'unlink':False },]
        if any(self.env.user.has_group(perm['group']) for perm in permissions):
            return any(self.env.user.has_group(perm['group']) and perm[operation] for perm in permissions)
        return super().check_access_rights(operation, raise_exception=raise_exception)

class Stock_MoveLine(models.Model):
    _inherit = ['stock.move.line']
    picking_type_id = fields.Many2one('stock.picking.type', store='True')


    @api.model
    def check_access_rights(self, operation, raise_exception=True):
        if self.env.su:
            return True
        permissions = [{'group':'smartbiz_stock.group_roles_inventory___move_readonly_6','read':True,'write':False,'create':False,'unlink':False },]
        if any(self.env.user.has_group(perm['group']) for perm in permissions):
            return any(self.env.user.has_group(perm['group']) and perm[operation] for perm in permissions)
        return super().check_access_rights(operation, raise_exception=raise_exception)

class Stock_Location(models.Model):
    _inherit = ['stock.location']
    capacity = fields.Float(string='Capacity')
    capacity_type = fields.Selection([('quantity','Quantity'),('weight','Weight'),('volume','Volume'),], string='Capacity Type')
    allow_negative_stock = fields.Boolean(string='Allow Negative Stock')


    @api.model
    def check_access_rights(self, operation, raise_exception=True):
        if self.env.su:
            return True
        permissions = [{'group':'smartbiz_stock.group_roles_inventory___configuaration_readonly_5','read':True,'write':False,'create':False,'unlink':False },]
        if any(self.env.user.has_group(perm['group']) for perm in permissions):
            return any(self.env.user.has_group(perm['group']) and perm[operation] for perm in permissions)
        return super().check_access_rights(operation, raise_exception=raise_exception)

class Stock_Route(models.Model):
    _inherit = ['stock.route']


    @api.model
    def check_access_rights(self, operation, raise_exception=True):
        if self.env.su:
            return True
        permissions = [{'group':'smartbiz_stock.group_roles_inventory___configuaration_readonly_5','read':True,'write':False,'create':False,'unlink':False },]
        if any(self.env.user.has_group(perm['group']) for perm in permissions):
            return any(self.env.user.has_group(perm['group']) and perm[operation] for perm in permissions)
        return super().check_access_rights(operation, raise_exception=raise_exception)

class Stock_Rule(models.Model):
    _inherit = ['stock.rule']


    @api.model
    def check_access_rights(self, operation, raise_exception=True):
        if self.env.su:
            return True
        permissions = [{'group':'smartbiz_stock.group_roles_inventory___configuaration_readonly_5','read':True,'write':False,'create':False,'unlink':False },]
        if any(self.env.user.has_group(perm['group']) for perm in permissions):
            return any(self.env.user.has_group(perm['group']) and perm[operation] for perm in permissions)
        return super().check_access_rights(operation, raise_exception=raise_exception)

class Stock_quantpackage(models.Model):
    _inherit = ['stock.quant.package']
    _sql_constraints = [
                ('uniq_name', 'unique(name)', "Name Exiting!"),
    ]
    name = fields.Char(store='True')


class Stock_Picking(models.Model):
    _inherit = ['stock.picking']
    lot = fields.Char(string='Lot')
    picking_order_ids = fields.Many2many('stock.picking', 'picking_picking_rel_1', 'picking_order_ids_1', 'picking_order_ids_2', string='Picking Order')
    warehouse_id = fields.Many2one('stock.warehouse', string='Warehouse', compute='_compute_warehouse_id', store=True)
    picking_type_id = fields.Many2one('stock.picking.type', store='True')
    transfer_request_id = fields.Many2one('smartbiz_stock.transfer_request', string='Transfer Request')
    name = fields.Char(string='Name', readonly=False)


    @api.depends('picking_type_id')
    def _compute_warehouse_id(self):
        for record in self:
            record.warehouse_id = record.picking_type_id.warehouse_id

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
        return super().action_confirm()

    @api.model
    def check_access_rights(self, operation, raise_exception=True):
        if self.env.su:
            return True
        permissions = [{'group':'smartbiz_stock.group_roles_inventory___move_readonly_6','read':True,'write':False,'create':False,'unlink':False },]
        if any(self.env.user.has_group(perm['group']) for perm in permissions):
            return any(self.env.user.has_group(perm['group']) and perm[operation] for perm in permissions)
        return super().check_access_rights(operation, raise_exception=raise_exception)

class SmartbizStock_StockReport(models.Model):
    _name = "smartbiz_stock.stock_report"
    _inherit = ['smartbiz.workflow_base', 'mail.thread', 'mail.activity.mixin']
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
        self.ensure_one()

        # Gọi hàm _create_view để tạo view với khoảng thời gian từ from_date đến to_date
        self.env['smartbiz_stock.inventory_report']._create_view(self.from_date, self.to_date)

        # Cập nhật trạng thái thành 'viewed'
        self.sudo().write({'state': 'viewed'})

        # Trả về action để hiển thị báo cáo với view tree, pivot và graph
        return {
            'type': 'ir.actions.act_window',
            'name': 'Inventory Report',
            'view_mode': 'tree,form,pivot,graph',
            'res_model': 'smartbiz_stock.inventory_report',  # Model của báo cáo
            'context':dict(
                self.env.context, 
                edit=False, 
                delete=False, 
                create=False
                ),
        }

        
        
    def save_excel(self,workbook,file_name):
        output = BytesIO()
        workbook.save(output)

        #workbook.close()

        # Tạo response
        file_data = base64.b64encode(output.getvalue())
        output.close()

        # Tạo attachment
        attachment = self.env['ir.attachment'].create({
            'name': file_name,
            'type': 'binary',
            'datas': file_data,
            'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            'res_model': self._name,
            'res_id': self.id
        })

        # Trả về action để download file
        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/%d?download=true' % attachment.id,
            'target': 'new',
        }
        
    def load_excel(self,file_name):
        current_dir = os.path.dirname(__file__)
        # Lùi lại hai cấp thư mục để đến thư mục gốc của module
        module_dir = os.path.abspath(os.path.join(current_dir, os.pardir))

        # Xây dựng đường dẫn đến file template
        template_path = os.path.join(module_dir, 'data', file_name)

        return load_workbook(template_path)

class SmartbizStock_TransferRequest(models.Model):
    _name = "smartbiz_stock.transfer_request"
    _inherit = ['smartbiz.workflow_base', 'mail.thread', 'mail.activity.mixin']
    _description = "Transfer Request"
    name = fields.Char(string='Request', default = 'New')
    date = fields.Datetime(string='Date')
    transfer_request_type_id = fields.Many2one('smartbiz_stock.transfer_request_type', string='Transfer Request Type')
    transfer_request_line_ids = fields.One2many('smartbiz_stock.transfer_request_line', 'transfer_request_id')
    picking_ids = fields.One2many('stock.picking', 'transfer_request_id')
    state = fields.Selection([('draft','Draft'),('done','Done'),], string= 'Status', readonly= False, copy = True, index = False, default = 'draft')


    def action_draft_create_order(self):
        Picking = self.env['stock.picking']
        Move    = self.env['stock.move']

        for record in self.filtered(lambda m: m.state != 'done'):
            pickings = {}

            for trl in record.transfer_request_line_ids:
                quantity_needed = trl.quantity
                product = trl.product_id
                lots_ids = trl.lots_ids.ids
                origin = record.name

                for trtd in sorted(record.transfer_request_type_id.transfer_request_type_detail_ids, key=lambda x: x.sequence):
                    picking_type   = trtd.picking_type_id
                    location_src   = picking_type.default_location_src_id
                    location_dest  = picking_type.default_location_dest_id

                    # build domain lọc quants — chỉ thêm điều kiện lot khi có
                    domain = [
                        ('location_id','child_of', location_src.id),
                        ('product_id','=', product.id),
                    ]
                    if lots_ids:
                        domain.append(('lot_id','in', lots_ids))
                    onhand = sum(self.env['stock.quant'].search(domain).mapped('quantity'))

                    if quantity_needed > onhand:
                        used_qty = onhand
                    else:
                        used_qty = quantity_needed
                    
                    if ('VW' in product.name or 'HANGER' in product.name) and onhand <= 0:
                        continue
                    
                    if used_qty < 0:
                        continue

                    key = picking_type.id
                    if used_qty > 0:
                        if key not in pickings:
                            pickings[key] = {
                                'picking_type': picking_type,
                                'location_src':  location_src,
                                'location_dest': location_dest,
                                'origin':        origin,
                                'transfer_request_id': record.id,
                                'products':      [],
                            }

                        pickings[key]['products'].append({
                            'product': product,
                            'quantity': quantity_needed,
                            'lots_ids': lots_ids,
                            'transfer_request_line_id': trl.id,
                        })

                        quantity_needed -= used_qty
                        if quantity_needed <= 0:
                            break

            # tạo pickings & moves chỉ với các products đã được append (used_qty>0)
            for picking_data in pickings.values():
                picking = Picking.create({
                    'picking_type_id':  picking_data['picking_type'].id,
                    'location_id':       picking_data['location_src'].id,
                    'location_dest_id':  picking_data['location_dest'].id,
                    'transfer_request_id': picking_data['transfer_request_id'],
                    'origin':            picking_data['origin'],
                })
                for prod in picking_data['products']:
                    Move.create({
                        'name':          prod['product'].display_name,
                        'product_id':    prod['product'].id,
                        'product_uom_qty': prod['quantity'],
                        'product_uom':   prod['product'].uom_id.id,
                        'picking_id':    picking.id,
                        'location_id':   picking_data['location_src'].id,
                        'location_dest_id': picking_data['location_dest'].id,
                        'transfer_request_line_id': prod['transfer_request_line_id'],
                        'lots':          prod['lots_ids'],
                    })
                picking.action_confirm()

            record.write({'state': 'done'})

        
        
    def _find_record(self,records):
        # Bước 1: Lọc ra các bản ghi có "số lượng" > 0
        valid_records = [record for record in records if record['onhand_quantity'] > 0]
        
        if len(valid_records) == 0:
            # Bước 6: Nếu không có bản ghi nào có "số lượng" > 0, lấy bản ghi có "kiểu điều chuyển" bằng "kiểu điều chuyển mặc định"
            default_record = next((record for record in records if record['picking_type'] == record['default_picking_type']), records[0] if records else None)
            return default_record
        
        if len(valid_records) == 1:
            # Bước 3: Nếu chỉ có một bản ghi "số lượng" > 0, lấy bản ghi đó
            return valid_records[0]
        
        # Bước 2: Kiểm tra xem trong số các bản ghi hợp lệ, có bản ghi nào "kiểu điều chuyển" bằng "kiểu điều chuyển mặc định" không
        default_transfer_record = next((record for record in valid_records if record['picking_type'] == record['default_picking_type']), None)
        
        if default_transfer_record:
            # Bước 5: Có bản ghi "kiểu điều chuyển" bằng "kiểu điều chuyển mặc định"
            return default_transfer_record
        else:
            # Bước 4: Lấy bản ghi có "mức độ quan trọng" lớn nhất
            return min(valid_records, key=lambda x: x['sequence'])
            
    def _get_default_picking_type(self,product):
        if '(VW' in product.name:
            return self.env['stock.picking.type'].search([('barcode','=','F58-COMP3-PICK')],limit=1)
        else:
            return self.env['stock.picking.type'].search([('barcode','=','F110-COMP3-PICK')],limit=1)

    @api.model
    def create(self, values):
        if values.get('name', 'New') == 'New':
           values['name'] = self.env['ir.sequence'].next_by_code('smartbiz_stock.transfer_request') or 'New'


        res = super().create(values)


        return res

class SmartbizStock_TransferRequestLine(models.Model):
    _name = "smartbiz_stock.transfer_request_line"
    _description = "Transfer Request Line"
    product_id = fields.Many2one('product.product', string='Product')
    lots_ids = fields.Many2many('stock.lot', string='Lots')
    quantity = fields.Float(string='Quantity')
    transfer_request_id = fields.Many2one('smartbiz_stock.transfer_request', string='Transfer Request')


class SmartbizStock_TransferRequestType(models.Model):
    _name = "smartbiz_stock.transfer_request_type"
    _description = "Transfer Request Type"
    name = fields.Char(string='Name')
    transfer_request_type_detail_ids = fields.One2many('smartbiz_stock.transfer_request_type_detail', 'transfer_request_type_id')


class SmartbizStock_TransferRequestTypeDetail(models.Model):
    _name = "smartbiz_stock.transfer_request_type_detail"
    _description = "Transfer Request Type Detail"
    sequence = fields.Integer(string='Sequence')
    picking_type_id = fields.Many2one('stock.picking.type', string='Picking Type')
    transfer_request_type_id = fields.Many2one('smartbiz_stock.transfer_request_type', string='Transfer Request Type')


class SmartbizStock_OnhandReport(models.Model):
    _inherit = ['smartbiz.nomenclature.report.mixin']                                                     
    _name = "smartbiz_stock.onhand_report"
    _rec_name = "product_id"
    _auto=False
    _description = "Onhand Report"
    location_id = fields.Many2one('stock.location', string='Location')
    product_id = fields.Many2one('product.product', string='Product')
    lot_id = fields.Many2one('stock.lot', string='Lot')
    package_id = fields.Many2one('stock.quant.package', string='Package')
    last_inventory_date = fields.Datetime(string='Last Inventory Date')
    quantity = fields.Float(string='Quantity')


    # ======= khai mixin ======
    def _aliases(self):
        return {'pt': 'product.template', 'sl': 'stock.lot'}

    def _base_view_xmlid(self):
        return 'smartbiz_stock.smartbiz_stock_onhand_report_tree'

    # ======= SQL gốc (đã chỉnh sửa) =======
    def _core_sql(self):
        return """
            SELECT
                sq.id            AS id,
                sq.location_id,
                sq.product_id,
                sq.lot_id,
                --[[EXTRA_SELECT]]
                sq.package_id,
                /* ngày kiểm kê cuối cùng (NULL nếu chưa kiểm kê) */
                MAX(
                    CASE WHEN sm.is_inventory THEN sm.date END
                )               AS last_inventory_date,
                sq.quantity
            FROM stock_quant sq
            /* ---- liên kết move‑line (LEFT JOIN để không loại quant nào) ---- */
            LEFT JOIN stock_move_line sml ON (
                (sq.lot_id IS NULL OR sq.lot_id = sml.lot_id)
                AND sq.product_id = sml.product_id
                AND (
                    /* xuất hoặc nhập khớp kho/kiện */
                    (sq.location_id = sml.location_id
                    AND (sq.package_id IS NULL OR sq.package_id = sml.package_id))
                OR (sq.location_id = sml.location_dest_id
                    AND (sq.package_id IS NULL OR sq.package_id = sml.result_package_id))
                )
            )
            /* chỉ ràng buộc is_inventory khi lấy ngày */
            LEFT JOIN stock_move sm ON sm.id = sml.move_id
            /* ---- thông tin sản phẩm & lô (LEFT JOIN để không lọt bỏ NULL) ---- */
            LEFT JOIN product_product  pp ON pp.id = sq.product_id
            LEFT JOIN product_template pt ON pt.id = pp.product_tmpl_id
            LEFT JOIN stock_lot        sl ON sl.id = sq.lot_id
            GROUP BY
                sq.id, sq.location_id, sq.product_id, sq.lot_id,
                sq.package_id, sq.quantity
                --[[EXTRA_GROUP]]
        """


    # ======= build view một lần khi server lên =======
    def init(self):
        self._rebuild_view()

class SmartbizStock_InventoryReport(models.Model):
    _inherit = ['smartbiz.nomenclature.report.mixin']                                                     
    _name = "smartbiz_stock.inventory_report"
    _rec_name = "product_id"
    _auto=False
    _description = "Inventory Report"
    warehouse_id = fields.Many2one('stock.warehouse', string='Warehouse')
    product_id = fields.Many2one('product.product', string='Product')
    lot_id = fields.Many2one('stock.lot', string='Lot')
    uom_id = fields.Many2one('uom.uom', string='UoM')
    initial_quantity = fields.Float(string='Initial Quantity')
    initial_weight = fields.Float(string='Initial Weight')
    normal_in_quantity = fields.Float(string='Normal In Quantity')
    normal_in_weight = fields.Float(string='Normal In Weight')
    adjustment_in_quantity = fields.Float(string='Adjustment In Quantity')
    adjustment_in_weight = fields.Float(string='Adjustment In Weight')
    total_in_quantity = fields.Float(string='Total In Quantity')
    total_in_weight = fields.Float(string='Total In Weight')
    normal_out_quantity = fields.Float(string='Normal Out Quantity')
    normal_out_weight = fields.Float(string='Normal Out Weight')
    adjustment_out_quantity = fields.Float(string='Adjustment Out Quantity')
    adjustment_out_weight = fields.Float(string='Adjustment Out Weight')
    total_out_quantity = fields.Float(string='Total Out Quantity')
    total_out_weight = fields.Float(string='Total Out Weight')
    final_quantity = fields.Float(string='Final Quantity')
    final_weight = fields.Float(string='Final Weight')
    currency_id = fields.Many2one('res.currency', string='Currency')
    initial_value = fields.Monetary(string='Initial Value')
    normal_in_value = fields.Monetary(string='Normal In Value')
    adjustment_in_value = fields.Monetary(string='Adjustment In Value')
    total_in_value = fields.Monetary(string='Total In Value')
    normal_out_value = fields.Monetary(string='Normal Out Value')
    adjustment_out_value = fields.Monetary(string='Adjustment Out Value')
    total_out_value = fields.Monetary(string='Total Out Value')
    final_value = fields.Monetary(string='Final Value')


    # ---------- khai mixin ----------
    def _aliases(self):
        return {'pt': 'product.template', 'sl': 'stock.lot'}

    def _base_view_xmlid(self):
        return 'smartbiz_stock.smartbiz_stock_inventory_report_tree'

    # ---------- SQL gốc + placeholder ----------
    def _core_sql(self):
        # rút gọn phần WITH ... SELECT ... tính toán cho ngắn
        return """
            WITH inventory_data AS (
                SELECT 
                    sml.product_id,
                    sml.lot_id,
                    pt.weight as product_weight,
                    uom.id as uom_id,  -- UOM (Đơn vị tính)
                    uom.factor as uom_factor,  -- Tỉ lệ chuyển đổi đơn vị tính
                    uom_category.name->>'en_US' as uom_category,  -- Trích xuất giá trị 'en_US' từ JSON của uom_category.name
                    sm.price_unit AS price_unit,  -- Price Unit from Stock Move
                    rc.currency_id,  -- Lấy currency_id từ bảng res_company
                    SUM(CASE WHEN sm.date < '{from_date} 00:00:00' AND sml.state = 'done' THEN sml.quantity ELSE 0 END) as initial_quantity,
                    
                    -- Normal In: Sản phẩm được nhập vào vị trí nội bộ và không phải là điều chỉnh tồn kho
                    SUM(CASE WHEN sm.date >= '{from_date} 00:00:00' AND sm.date <= '{to_date} 23:59:59' 
                             AND sml.state = 'done' 
                             AND loc_dest.usage = 'internal' 
                             AND loc_src.usage != 'internal'  -- Loại bỏ giao dịch nội bộ trong cùng một kho
                             AND loc_src.usage != 'inventory'  -- Loại bỏ điều chỉnh tồn kho
                             THEN sml.quantity ELSE 0 END) as normal_in_quantity,
                    
                    -- Adjustment In: Sản phẩm được nhập vào từ điều chỉnh tồn kho
                    SUM(CASE WHEN sm.date >= '{from_date} 00:00:00' AND sm.date <= '{to_date} 23:59:59' 
                             AND sml.state = 'done' 
                             AND loc_dest.usage = 'internal'  -- Nhập vào kho nội bộ
                             AND loc_src.usage = 'inventory'  -- Nguồn từ điều chỉnh tồn kho
                             THEN sml.quantity ELSE 0 END) as adjustment_in_quantity,
                    
                    -- Normal Out: Sản phẩm được xuất khỏi kho đến một vị trí không phải là điều chỉnh tồn kho
                    SUM(CASE WHEN sm.date >= '{from_date} 00:00:00' AND sm.date <= '{to_date} 23:59:59' 
                             AND sml.state = 'done' 
                             AND loc_src.usage = 'internal'  -- Xuất từ kho nội bộ
                             AND loc_dest.usage != 'internal'  -- Không phải di chuyển nội bộ trong kho
                             AND loc_dest.usage != 'inventory'  -- Không phải điều chỉnh tồn kho
                             THEN sml.quantity ELSE 0 END) as normal_out_quantity,
                    
                    -- Adjustment Out: Sản phẩm được xuất từ điều chỉnh tồn kho
                    SUM(CASE WHEN sm.date >= '{from_date} 00:00:00' AND sm.date <= '{to_date} 23:59:59' 
                             AND sml.state = 'done' 
                             AND loc_src.usage = 'inventory'  -- Nguồn từ điều chỉnh tồn kho
                             AND loc_dest.usage = 'internal'  -- Xuất vào kho nội bộ
                             THEN sml.quantity ELSE 0 END) as adjustment_out_quantity,
                    
                    -- Final Quantity: Tổng số lượng tồn kho cuối kỳ
                    SUM(CASE WHEN sm.date <= '{to_date} 23:59:59' AND sml.state = 'done' THEN sml.quantity ELSE 0 END) as final_quantity,
                    
                    -- Warehouse ID (dựa trên nguồn hoặc đích)
                    CASE WHEN loc_src.usage = 'internal' THEN loc_src.warehouse_id ELSE loc_dest.warehouse_id END as warehouse_id
                FROM 
                    stock_move_line sml
                JOIN
                    stock_move sm ON sml.move_id = sm.id
                JOIN
                    stock_location loc_src ON sml.location_id = loc_src.id
                JOIN
                    stock_location loc_dest ON sml.location_dest_id = loc_dest.id
                JOIN
                    product_product pp ON sml.product_id = pp.id
                JOIN
                    product_template pt ON pp.product_tmpl_id = pt.id
                JOIN
                    uom_uom uom ON sml.product_uom_id = uom.id  -- Thêm UOM (Đơn vị tính) vào JOIN
                JOIN
                    uom_category ON uom.category_id = uom_category.id  -- Thêm uom_category vào JOIN
                JOIN
                    res_company rc ON sm.company_id = rc.id  -- Thêm liên kết với bảng res_company để lấy currency_id
                WHERE sml.state = 'done'
                GROUP BY 
                    sml.product_id, sml.lot_id, pt.weight, sm.price_unit, rc.currency_id, uom.id, uom.factor, uom_category.name, loc_src.warehouse_id, loc_dest.warehouse_id, loc_src.usage, loc_dest.usage
            )
            SELECT 
                ROW_NUMBER() OVER() as id,
                inv.warehouse_id,
                inv.product_id,
                inv.lot_id,
                --[[EXTRA_SELECT]]
                inv.uom_id,  -- UOM ID (Đơn vị tính)
                inv.currency_id,  -- Thêm trường currency_id vào view
                inv.initial_quantity,
                
                -- Tính trọng lượng dựa trên UOM (Nếu thuộc nhóm khối lượng, sử dụng factor, nếu không, sử dụng weight)
                CASE WHEN inv.uom_category = 'Weight' THEN inv.initial_quantity / inv.uom_factor ELSE inv.initial_quantity * inv.product_weight END as initial_weight,
                
                inv.normal_in_quantity,
                CASE WHEN inv.uom_category = 'Weight' THEN inv.normal_in_quantity / inv.uom_factor ELSE inv.normal_in_quantity * inv.product_weight END as normal_in_weight,
                
                inv.adjustment_in_quantity,
                CASE WHEN inv.uom_category = 'Weight' THEN inv.adjustment_in_quantity / inv.uom_factor ELSE inv.adjustment_in_quantity * inv.product_weight END as adjustment_in_weight,
                
                (inv.normal_in_quantity + inv.adjustment_in_quantity) as total_in_quantity,
                (CASE WHEN inv.uom_category = 'Weight' THEN inv.normal_in_quantity / inv.uom_factor ELSE inv.normal_in_quantity * inv.product_weight END 
                + CASE WHEN inv.uom_category = 'Weight' THEN inv.adjustment_in_quantity / inv.uom_factor ELSE inv.adjustment_in_quantity * inv.product_weight END) as total_in_weight,
                
                inv.normal_out_quantity,
                CASE WHEN inv.uom_category = 'Weight' THEN inv.normal_out_quantity / inv.uom_factor ELSE inv.normal_out_quantity * inv.product_weight END as normal_out_weight,
                
                inv.adjustment_out_quantity,
                CASE WHEN inv.uom_category = 'Weight' THEN inv.adjustment_out_quantity / inv.uom_factor ELSE inv.adjustment_out_quantity * inv.product_weight END as adjustment_out_weight,
                
                (inv.normal_out_quantity + inv.adjustment_out_quantity) as total_out_quantity,
                (CASE WHEN inv.uom_category = 'Weight' THEN inv.normal_out_quantity / inv.uom_factor ELSE inv.normal_out_quantity * inv.product_weight END 
                + CASE WHEN inv.uom_category = 'Weight' THEN inv.adjustment_out_quantity / inv.uom_factor ELSE inv.adjustment_out_quantity * inv.product_weight END) as total_out_weight,
                
                inv.final_quantity,
                CASE WHEN inv.uom_category = 'Weight' THEN inv.final_quantity / inv.uom_factor ELSE inv.final_quantity * inv.product_weight END as final_weight,
                
                -- Calculating values based on price_unit
                inv.initial_quantity * inv.price_unit as initial_value,
                inv.normal_in_quantity * inv.price_unit as normal_in_value,
                inv.adjustment_in_quantity * inv.price_unit as adjustment_in_value,
                (inv.normal_in_quantity * inv.price_unit + inv.adjustment_in_quantity * inv.price_unit) as total_in_value,
                inv.normal_out_quantity * inv.price_unit as normal_out_value,
                inv.adjustment_out_quantity * inv.price_unit as adjustment_out_value,
                (inv.normal_out_quantity * inv.price_unit + inv.adjustment_out_quantity * inv.price_unit) as total_out_value,
                inv.final_quantity * inv.price_unit as final_value
            FROM 
                inventory_data inv
            JOIN product_product pp ON pp.id = inv.product_id
            JOIN stock_lot sl  ON sl.id = inv.lot_id
            LEFT JOIN product_template pt ON pp.product_tmpl_id = pt.id
                    
           
        """

    # ---------- rebuild theo khoảng ngày ----------
    def _create_view(self, from_date, to_date):
        sqltl = self._sql_tools() 
        sel, grp, labels = sqltl.select_group(self._name, self._aliases())

        # thay placeholder
        base_sql = self._core_sql()
        sql = base_sql.replace("--[[EXTRA_SELECT]]", sel and f"{sel},\n " or "")
        sql = sql.replace("--[[EXTRA_GROUP]]",  grp and f", {grp}" or "")
        sql = sql.format(from_date=from_date, to_date=to_date)
        
        #raise UserError("sel %s grp %s labels %s set Labels %s sql %s" % (sel,grp,labels,{self._name: set(labels)},sql))
        
        # sqltl.sync_fields({self._name: labels})
        
        # sqltl.ensure_view_ext(self._name, self._base_view_xmlid(), labels)

        tools.drop_view_if_exists(self._cr, self._table)
        self._cr.execute(f"CREATE OR REPLACE VIEW {self._table} AS ({sql})")

    # ---------- init ----------
    def init(self):
        today = fields.Date.today()
        self._create_view(today, today)

class stock_packagelevel(models.Model):
    _inherit = ['stock.package_level']
    name = fields.Char(store='True')


    def _generate_moves(self):
        return

