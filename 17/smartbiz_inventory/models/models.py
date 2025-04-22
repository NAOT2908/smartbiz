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


class InventoryPeriod(models.Model):
    _name = 'smartbiz.inventory.period'
    _description = 'Inventory Period'

    name = fields.Char(string="Period Name", required=True)
    date_start = fields.Date(string="Start Date", required=True)
    date_end = fields.Date(string="End Date", required=True)
    company_id = fields.Many2one('res.company', string="Company", required=True, default=lambda self: self.env.company)
    inventory_ids = fields.One2many('smartbiz.inventory', 'inventory_period_id', string="Inventories")

class Inventory(models.Model):
    _name = 'smartbiz.inventory'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = 'Stock Inventory'

    name = fields.Char(string="Inventory Name", required=True, default=lambda self: self.env['ir.sequence'].next_by_code('smartbiz.inventory'))
    date = fields.Datetime(string="Inventory Date", default=fields.Datetime.now, required=True)
    company_id = fields.Many2one('res.company', string="Company", required=True, default=lambda self: self.env.company)
    product_ids = fields.Many2many('product.product', string="Products",
                                   default=lambda self: self.env[
                                       'product.product'].search([], limit=1),
                                   help="Select multiple products "
                                        "from the list.")
    category_ids = fields.Many2many('product.category', string="Category",
                                    default=lambda self: self._default_categ_ids(),
                                    help="Select multiple categories "
                                         "from the list")
    warehouse_ids = fields.Many2many('stock.warehouse', string="Warehouse",
                                     default=lambda self: self._default_warehouse_ids(),
                                     help="Select multiple warehouses "
                                          "from the list.")
    user_id = fields.Many2one('res.users', string="Responsible User", default=lambda self: self.env.user)
    inventory_period_id = fields.Many2one('smartbiz.inventory.period', string="Inventory Period", required=True)
    inventory_location_ids = fields.Many2many('stock.location', string="Inventory Locations")
    line_ids = fields.One2many('smartbiz.inventory.line', 'inventory_id', string="Inventory Lines")
    line_count = fields.Integer(string="Line Count", compute="_compute_line_count")
    set_count = fields.Selection([
        ('empty', 'Empty'),
        ('set', 'Set Quantity'),
    ], string="Số lượng", default='empty')
    
    state = fields.Selection([
        ('draft', 'Draft'),
        ('in_progress', 'In Progress'),
        ('done', 'Done'),
        ('cancel', 'Cancel'),
    ], string="State", default='draft')

    @api.depends('line_ids')
    def _compute_line_count(self):
        for record in self:
            count = record.line_ids.search_count([('inventory_id', '=', record.id)])
            record.line_count = count
    
    def action_lines(self):
        action = self.env["ir.actions.actions"]._for_xml_id("smartbiz_inventory.action_smartbiz_inventory_line")
        context = eval(action['context'])
        context.update(dict(self._context,default_inventory_id=self.id))
        action['context'] = context
        action['domain'] = [('inventory_id', '=', self.id)]

        return action
    
    def _get_fields(self,model):
        if model == 'mrp.production':
            return ['name','state','product_id','product_uom_id','product_uom_qty','qty_produced','qty_producing','date_start','date_deadline','date_finished','company_id','user_id']
        if model == 'stock.move':
            return ['state','date','date_deadline','product_id','product_uom','product_uom_qty','quantity','product_qty','location_id','location_dest_id']
        if model == 'stock.move.line':
            return ['state','move_id','date','product_id','product_uom_id','quantity','location_id','location_dest_id','package_id','result_package_id','lot_id']
        if model == 'product.product':
            return ['barcode', 'default_code', 'tracking', 'display_name', 'uom_id']
        if model == 'stock.location':
            return ['display_name', 'barcode', 'parent_path']
        if model == 'stock.package.type':
            return ['barcode', 'name']
        if model == 'stock.quant.package':
            return ['name','location_id']
        if model == 'stock.lot':
            return ['name', 'ref', 'product_id','expiration_date','create_date','product_qty']
        if model == 'uom.uom':
            return ['name','category_id','factor','rounding',]
        if model == 'stock.quant':
            return ['product_id','location_id','inventory_date','inventory_quantity','inventory_quantity_set','quantity','product_uom_id','lot_id','package_id','owner_id','inventory_diff_quantity','user_id',]
        return []
    
    
    def _default_categ_ids(self):
        """Return default category to selection field."""
        category = self.env['product.product'].search(
            [], limit=1).product_tmpl_id.categ_id
        return [(6, 0, [category.id])] if category else []

    def _default_warehouse_ids(self):
        """Return default warehouse to selection field."""
        warehouse = self.env['stock.warehouse'].search([], limit=1)
        return [(6, 0, [warehouse.id])] if warehouse else []
    
    def action_start(self):
        """ Bắt đầu kiểm kê - lọc danh sách kiểm kê theo location nếu có """
        self.state = 'in_progress'
        self.line_ids.unlink()
        self._generate_inventory_lines()
    
    def action_cancel(self):
        """ Bắt đầu kiểm kê - lọc danh sách kiểm kê theo location nếu có """
        self.state = 'cancel'
        self.line_ids.unlink()

    def _generate_inventory_lines(self):
        """Tạo danh sách kiểm kê dựa trên location hoặc warehouse nếu có"""
        domain = [('company_id', '=', self.company_id.id)]

        if self.product_ids:
            domain.append(('product_id', 'in', self.product_ids.ids))
        if self.category_ids:
            domain.append(('product_categ_id', 'in', self.category_ids.ids))

        location_domain = []

        # Nếu có warehouse_ids, lấy toàn bộ vị trí con của các kho
        if self.warehouse_ids:
            for warehouse in self.warehouse_ids:
                warehouse_locations = self.env['stock.location'].search([
                    ('id', 'child_of', warehouse.view_location_id.id)
                ]).ids
                location_domain.extend(warehouse_locations)

        # Nếu có inventory_location_ids, chỉ dùng danh sách này và bỏ qua vị trí từ kho
        if self.inventory_location_ids:
            location_domain = self.inventory_location_ids.ids

        # Thêm domain lọc theo vị trí nếu có dữ liệu hợp lệ
        if location_domain:
            domain.append(('location_id', 'in', location_domain))

        quants = self.env['stock.quant'].search(domain)

        vals_list = [{
            'inventory_id': self.id,
            'product_id': quant.product_id.id,
            'lot_id': quant.lot_id.id if quant.lot_id else False,
            'package_id': quant.package_id.id if quant.package_id else False,
            'location_id': quant.location_id.id,
            'company_id': self.company_id.id,
            'quantity_before': quant.quantity,
            'quantity_counted': 0 if self.set_count == 'empty' else quant.quantity,
            'quant_id': quant.id,
            'note': '',
        } for quant in quants]

        if vals_list:
            self.env['smartbiz.inventory.line'].create(vals_list)
    def action_validate(self):
        """ Xác nhận kiểm kê - lưu vào lịch sử nhưng KHÔNG cập nhật stock.quant ngay """
        self.state = 'done'
        for line in self.line_ids:
            line.write({'state': 'done'})
            self.env['smartbiz.inventory.history'].create({
                'inventory_id': self.id,
                'name': self.name,
                'product_id': line.product_id.id,
                'lot_id': line.lot_id.id if line.lot_id else False,
                'package_id': line.package_id.id if line.package_id else False,
                'location_id': line.location_id.id,
                'company_id': self.company_id.id,
                'user_id': self.user_id.id if self.user_id else False,
                'quantity_before': line.quantity_before,
                'quantity_after': line.quantity_counted,
                'difference': line.difference,
                'date': fields.Datetime.now(),
                'note': line.note,
            })
        
            quants = self.env['stock.quant'].search([('id', '=', line.quant_id.id)])

            if quants:
                for quant in quants:
                    quant.inventory_quantity = line.quantity_counted
                    if line.package_id:
                        quant.package_id = line.package_id.id
            else:
                quant = self.env['stock.quant'].create({
                    'product_id': line.product_id.id,
                    'location_id': line.location_id.id,
                    'lot_id': line.lot_id.id if line.lot_id else False,
                    'package_id': line.package_id.id if line.package_id else False,
                    'company_id': self.company_id.id,
                    'quantity': 0,
                })
                quant.inventory_quantity = line.quantity_counted
    
    def apply_inventory(self, inventory_id, data):
        
        inventory = self.browse(inventory_id)
        if not inventory:
            return  

        data_ids = [item["id"] for item in data]  
        lines_to_update = inventory.line_ids.filtered(
            lambda l: l.state == 'counting' and l.id in data_ids
        )

        if lines_to_update:
            lines_to_update.write({'state': 'done'})
        
        return self.get_data(inventory_id)

        
    def open_confirm_wizard(self):
        return {
            'name': 'Xác nhận kiểm kê',
            'type': 'ir.actions.act_window',
            'res_model': 'smartbiz.inventory.confirm.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_inventory_id': self.id},
        } 
    
    def open_cancel_wizard(self):
        return {
            'name': 'Hủy kiểm kê',
            'type': 'ir.actions.act_window',
            'res_model': 'smartbiz.inventory.cancel.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_inventory_id': self.id},
        }
    def get_order(self):
        """Lấy danh sách các phiếu kiểm kê đang thực hiện, kèm theo chi tiết dòng kiểm kê"""
        
        current_user = self.env.user
        inventories = self.env['smartbiz.inventory'].search([('state', '=', 'in_progress'),'|',
        ('user_id', '=', current_user.id),
        ('user_id', '=', False),])
        users = self.env['res.users'].search([]).read(['name','barcode'], load=False)
        result = []
        for inventory in inventories:
            if not inventory.user_id:
                inventory.user_id = current_user
            
            lines = []
            for line in inventory.line_ids:
                lines.append({
                    'id': line.id,
                    'product_id': line.product_id.id,
                    'product_name': line.product_id.display_name,
                    'product_image': line.product_id.image_1920,
                    'product_uom_id': line.product_id.uom_id.id if line.product_id else False,
                    'product_uom_name': line.product_id.uom_id.name if line.product_id else '',
                    'lot_id': line.lot_id.id if line.lot_id else False,
                    'lot_name': line.lot_id.name if line.lot_id else '',
                    'package_id': line.package_id.id if line.package_id else False,
                    'package_name': line.package_id.name if line.package_id else '',
                    'location_id': line.location_id.id,
                    'location_name': line.location_id.display_name,
                    'quantity_before': line.quantity_before,
                    'quantity_counted': line.quantity_counted,
                    'difference': line.difference,
                    'quant_id': line.quant_id.id if line.quant_id else False,
                })
            
            result.append({
                'id': inventory.id,
                'name': inventory.name,
                'state': inventory.state,
                'company_id': inventory.company_id.id,
                'company_name': inventory.company_id.name,
                'date': inventory.date,
                'user_id': inventory.user_id.id,
                'lines': lines,
            })
            
        data = {
        'orders':result,
        'users':users
        }
        
        return data

    
    def get_data(self, inventory_id):
        """Lấy dữ liệu kiểm kê chi tiết theo ID"""
        inventory = self.browse(inventory_id)
        if not inventory.exists():
            return {'error': 'Inventory not found'}

        lines = inventory.line_ids
        products = lines.mapped('product_id')
        lots = lines.mapped('lot_id').filtered(lambda l: l)
        locations = lines.mapped('location_id')
        packages = lines.mapped('package_id').filtered(lambda p: p)

        lines_data = [{
            'id': line.id,
            'product_id': line.product_id.id if line.product_id else False,
            'product_name': line.product_id.display_name if line.product_id else '',
            'product_image': line.product_id.image_1920 if line.product_id else False,
            'product_uom_id': line.product_id.uom_id.id if line.product_id else False,
            'product_uom_name': line.product_id.uom_id.name if line.product_id else '',
            'lot_id': line.lot_id.id if line.lot_id else False,
            'lot_name': line.lot_id.name if line.lot_id else '',
            'location_id': line.location_id.id if line.location_id else False,
            'location_name': line.location_id.display_name if line.location_id else '',
            'package_id': line.package_id.id if line.package_id else False,
            'package_name': line.package_id.name if line.package_id else '',
            'quantity_before': line.quantity_before,
            'quantity_counted': line.quantity_counted,
            'difference': line.difference,
            'state': line.state,
            'note': line.note,
        } for line in lines]
        
        data = {
            'inventory': inventory.read(['id', 'name', 'state', 'company_id', 'user_id', 'date'])[0],
            'lines': lines_data,
            'products': products.read(['id', 'name', 'barcode', 'default_code', 'uom_id']) if products else [],
            'lots': lots.read(['id', 'name', 'product_id']) if lots else [],
            'locations': locations.read(['id', 'name', 'barcode']) if locations else [],
            'packages': packages.read(['id', 'name']) if packages else [],
            'company_id': inventory.company_id.id,
            'user_id': inventory.user_id.id,
        }
        return data
    
    def get_inventory_barcode_data(self,barcode,filters,barcodeType):
        """
        Tìm kiếm dữ liệu liên quan đến mã vạch trong bối cảnh 'stock.quant'.
        Args:
            barcode (str): Mã vạch được quét.
            filters (dict): Các bộ lọc bổ sung, ví dụ: `{'product_id': X}`.
            barcodeType (str): Loại mã vạch (product, location, lot, package).
        Returns:
            dict: Dữ liệu liên quan đến mã vạch hoặc False nếu không tìm thấy.
        """
        if barcodeType:
            if barcodeType == 'products':
                # Tìm kiếm sản phẩm theo mã vạch
                record = self.env['product.product'].search_read([('barcode', '=', barcode)], limit=1,
                                                                 fields=self._get_fields('product.product'))
            elif barcodeType == 'locations':
                # Tìm kiếm vị trí theo mã vạch
                record = self.env['stock.location'].search_read([('barcode', '=', barcode)], limit=1,
                                                                 fields=self._get_fields('stock.location'))
            elif barcodeType == 'lots':
                # Tìm kiếm lô hàng theo mã vạch và sản phẩm (nếu có)
                record = self.env['stock.lot'].search_read([('name', '=', barcode), ('product_id', '=', filters.get('product_id'))], limit=1,
                                                           fields=self._get_fields('stock.lot'))
            elif barcodeType == 'packages':
                # Tìm kiếm bao bì (package) theo mã vạch
                record = self.env['stock.quant.package'].search([('name', '=', barcode)], limit=1)
                if record:
                    # Xử lý package và các thông tin liên quan như sản phẩm, vị trí, số lượng, v.v.
                    record = self.env['stock.quant.package'].search([('name', '=', barcode)], limit=1)
                    if record:
                        products = [
                            {
                                'product_id': quant.product_id.id,
                                'location_id': quant.location_id.id,
                                'quantity': quant.quantity,
                                'lot_id': quant.lot_id.id,
                                'lot_name': quant.lot_id.name,
                                'product_uom_id': quant.product_id.uom_id.id,
                                'location_name': quant.location_id.display_name,
                                'available_quantity': quant.available_quantity,
                                'expiration_date': quant.lot_id.expiration_date,
                            }
                            for quant in record.quant_ids
                        ]
                        return {
                            'id': record.id,
                            'name': record.name,
                            'location': record.location_id.id,
                            'location_name': record.location_id.display_name,
                            'products': products,
                        }
            if record:
                return {'barcode': barcode, 'match': True, 'barcodeType': barcodeType, 'record': record[0] if isinstance(record, list) else record, 'fromCache': False}
        else:
            # Nếu không có `barcodeType`, kiểm tra lần lượt với các loại mã vạch
            if filters:
                # Tìm kiếm lô hàng (lot) theo mã vạch và sản phẩm (nếu có)
                record = self.env['stock.lot'].search_read([('name', '=', barcode), ('product_id', '=', filters.get('product_id'))], limit=1,
                                                           fields=self._get_fields('stock.lot'))
                if record:
                    return {'barcode': barcode, 'match': True, 'barcodeType': 'lots', 'record': record[0], 'fromCache': False}

            # Tìm kiếm sản phẩm theo mã vạch
            record = self.env['product.product'].search_read([('barcode', '=', barcode)], limit=1,
                                                             fields=self._get_fields('product.product'))
            if record:
                return {'barcode': barcode, 'match': True, 'barcodeType': 'products', 'record': record[0], 'fromCache': False}

            # Tìm kiếm vị trí theo mã vạch
            record = self.env['stock.location'].search_read([('barcode', '=', barcode)], limit=1,
                                                             fields=self._get_fields('stock.location'))
            if record:
                return {'barcode': barcode, 'match': True, 'barcodeType': 'locations', 'record': record[0], 'fromCache': False}

            # Tìm kiếm bao bì (package) theo mã vạch
            record = self.env['stock.quant.package'].search([('name', '=', barcode)], limit=1)
            if record:
                # Xử lý package và các thông tin liên quan
                products = []
                for quant in record.quant_ids:
                    product_id = quant.product_id.id
                    product_uom_id = quant.product_id.uom_id.id
                    location_id = quant.location_id.id
                    location_name = quant.location_id.display_name
                    quantity = quant.quantity
                    available_quantity = quant.available_quantity
                    lot_id = quant.lot_id.id
                    lot_name = quant.lot_id.name
                    expiration_date = quant.lot_id.expiration_date
                    products.append(
                        {'product_id': product_id, 'location_id': location_id, 'quantity': quantity, 
                         'lot_id': lot_id, 'lot_name': lot_name, 'product_uom_id': product_uom_id, 
                         'location_name': location_name, 'available_quantity': available_quantity, 
                         'expiration_date': expiration_date}
                    )
                record = {'id': record.id, 'name': record.name, 'location': record.location_id.id,
                          'location_name': record.location_id.display_name, 'products': products}
                return {'barcode': barcode, 'match': True, 'barcodeType': 'packages', 'record': record, 'fromCache': False}

        return {'barcode': barcode, 'match': False, 'barcodeType': barcodeType, 'record': False, 'fromCache': False}

    def process_barcode_scan(self, inventory_id, barcode_data):
        """
        Xử lý khi quét barcode trong kiểm kê kho.
        barcode_data gồm:
        - barcode: mã vạch quét
        - barcodeType: loại barcode (packages, locations, products, lots)
        - record: dữ liệu liên quan
        """
        inventory = self.env["smartbiz.inventory"].browse(inventory_id)
        if not inventory.exists():
            return {"error": "Inventory not found!"}

        scanned_type = barcode_data.get("barcodeType")
        record = barcode_data.get("record")

        if not scanned_type or not record:
            return {"error": "Dữ liệu barcode không hợp lệ!"}

        # Xử lý khi quét Package
        if scanned_type == "packages":
            package_id = record.get("id")
            package_products = record.get("products", [])

            for product in package_products:
                # Kiểm tra từng product có trong inventory chưa
                existing_product_line = inventory.line_ids.filtered(
                    lambda l: l.inventory_id.id == inventory_id
                    and l.product_id.id == product["product_id"]
                    and l.location_id.id == product["location_id"]
                    and l.package_id.id == package_id
                    # and l.state not in ["done", "counting"]
                )

                if existing_product_line:
                    existing_product_line.filtered(lambda l: l.state not in ["done", "counting"]).write({
                        "quantity_counted": product["quantity"],
                        "state": "counting",
                    })
                else:
                    inventory.line_ids.create({
                        "inventory_id": inventory.id,
                        "product_id": product["product_id"],
                        "location_id": product["location_id"],
                        "quantity_before": product["quantity"],
                        "quantity_counted": product["quantity"],  # Cộng dồn số lượng
                        "lot_id": product["lot_id"],
                        "package_id": package_id,
                        "state": "counting",
                    })

            return self.get_data(inventory_id)
        
        # if scanned_type == "products":
        #     product_id = record.get("id")
            
        #     inventory.line_ids.create({
        #         "inventory_id": inventory.id,
        #         "product_id": product_id,
        #         "location_id": location_id,
        #         "quantity_before": 1,
        #         "quantity_counted": 1,
        #         "state": "counting",
        #     })

        #     return self.get_data(inventory_id)

        return {"error": "Loại barcode không được hỗ trợ!"}  
  
    def save_order(self, inventory_id, data):
        """Cập nhật hoặc tạo mới dòng kiểm kê"""
        
        # Đảm bảo quantity luôn có giá trị hợp lệ
        quantity = float(data['quantity_counted']) if data.get('quantity_counted') else 0.0  
        line_obj = self.env['smartbiz.inventory.line']

        if data.get('id'):  # Nếu đã có ID, cập nhật bản ghi
            line = line_obj.browse(data['id'])
            if line.exists():
                line.write({
                    'location_id': data['location_id'],
                    'lot_id': data['lot_id'],
                    'package_id': data.get('package_id', False),
                    'state': data.get('state', 'counting'),
                    'quantity_counted': quantity,
                    'note': data.get('note', line.note)  # Tránh lỗi nếu 'note' không có trong data
                })
            else:
                return {'success': False, 'message': 'Inventory line not found'}
        else:  # Nếu chưa có ID, tạo mới bản ghi
            # product = self.env['product.product'].browse(data['product_id'])
            line = line_obj.create({
                'inventory_id': inventory_id,
                'product_id': data['product_id'],
                # 'product_uom_id': product.uom_id.id if product.exists() else False,
                'location_id': data['location_id'],
                'lot_id': data['lot_id'],
                'package_id': data.get('package_id', False),
                'state': 'counting',
                'quantity_before': 0,
                'quantity_counted': data.get('quantity_counted', 0),
                'note': data.get('note', '')  # Mặc định note là chuỗi rỗng
            })

        return self.get_data(inventory_id)

    def create_lot(self,inventory_id,product_id,company_id,lot_name = False):
        if lot_name:
            lot_id = self.env['stock.lot'].search([['product_id','=',product_id],['name','=',lot_name],['company_id','=',company_id]],limit=1)
            if not lot_id:
                lot_id = self.env['stock.lot'].create({'product_id':product_id,'name':lot_name,'company_id':company_id})
        else:
            lot_id = self.env['stock.lot'].create({'product_id':product_id,'company_id':company_id})
        data = self.get_data(inventory_id)
        data['lot_id'] = lot_id.id
        data['lot_name'] = lot_id.name
        return data
    
    def delete_inventory_line(self,inventory_id,inventory_line_id):
        ml = self.env['smartbiz.inventory.line'].browse(inventory_line_id)
        if ml.exists():
            ml.unlink()
        return self.get_data(inventory_id)
        
    
class InventoryLine(models.Model):
    _name = 'smartbiz.inventory.line'
    _description = 'Inventory Line'

    inventory_id = fields.Many2one('smartbiz.inventory', string="Inventory", required=True, ondelete='cascade')
    product_id = fields.Many2one('product.product', string="Product", required=True)
    lot_id = fields.Many2one('stock.lot', string="Lot/Serial")
    package_id = fields.Many2one('stock.quant.package', string="Package")
    location_id = fields.Many2one('stock.location', string="Location", required=True)
    company_id = fields.Many2one('res.company', string="Company", required=True, default=lambda self: self.env.company)
    quantity_before = fields.Float(string="Inventory Quantity", readonly=True)
    quantity_counted = fields.Float(string="Counted Quantity")
    difference = fields.Float(string="Difference", compute="_compute_difference")
    note = fields.Html(string="Note")

    quant_id = fields.Many2one('stock.quant', string="Related Stock Quant")
    state = fields.Selection([
        ('pending', 'Chờ kiểm kê'),
        ('counting', 'Đang kiểm kê'),
        ('done', 'Đã kiểm kê'),
        ('error', 'Lỗi')
    ], string='Trạng thái', default='pending')

    @api.depends('quantity_before', 'quantity_counted')
    def _compute_difference(self):
        for line in self:
            line.difference = line.quantity_counted - line.quantity_before
            

class InventoryHistory(models.Model):
    _name = "smartbiz.inventory.history"
    _description = "Inventory History"
    _order = "date desc"

    name = fields.Char(string="Reference", required=True, copy=False, readonly=True, default=lambda self: _("New"))
    inventory_id = fields.Many2one("smartbiz.inventory", string="Inventory Session", required=True, ondelete="cascade")
    user_id = fields.Many2one("res.users", string="User", required=True, default=lambda self: self.env.user)
    date = fields.Datetime(string="Date", required=True, default=fields.Datetime.now)
    location_id = fields.Many2one("stock.location", string="Location", required=True)
    product_id = fields.Many2one("product.product", string="Product", required=True)
    quantity_before = fields.Float(string="Quantity Before", readonly=True)
    quantity_after = fields.Float(string="Quantity After", readonly=True)
    difference = fields.Float(string="Difference", compute="_compute_difference")
    lot_id = fields.Many2one("stock.lot", string="Lot/Serial Number")
    package_id = fields.Many2one("stock.quant.package", string="Package")
    company_id = fields.Many2one("res.company", string="Company", required=True, default=lambda self: self.env.company)
    note = fields.Html(string="Ghi chú")
    @api.model
    def create(self, vals):
        if vals.get("name", _("New")) == _("New"):
            vals["name"] = self.env["ir.sequence"].next_by_code("smartbiz.inventory.history") or _("New")
        return super().create(vals)
    
    @api.depends("quantity_before", "quantity_after")
    def _compute_difference(self):
        for rec in self:
            rec.difference = rec.quantity_after - rec.quantity_before

    def unlink(self):
        if not self.env.user.has_group('smartbiz_inventory.group_can_delete_historyline'):
            raise UserError(_("Bạn không có quyền xóa dòng lịch sử!"))
        return super().unlink()
      