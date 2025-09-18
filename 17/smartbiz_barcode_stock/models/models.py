# -*- coding: utf-8 -*-

from odoo.osv import expression
from odoo import models, fields, api, exceptions, tools
from odoo.tools.translate import _
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

class Stock_PickingType(models.Model):
    _inherit = ['stock.picking.type']
    name = fields.Char(store='True')


    def open_picking_kanban(self):       
        view_id = self.env.ref('smartbiz_barcode_stock.stock_picking_kanban').id       
        context = {
            'search_default_picking_type_id': [self.id],
            #'search_default_to_do_transfers':1,
            'search_default_available':1,
            'default_picking_type_id': self.id,
            'default_company_id': self.company_id.id,
        }       
        action = {
            'type': 'ir.actions.act_window',       
            'views':[(view_id,'kanban')],
            'name': self.display_name,
            'res_model': 'stock.picking',
            'target': 'current',
            'context':context
        }
        return action

class Stock_Picking(models.Model):
    _inherit = ['stock.picking']
    name = fields.Char(store='True')

    @api.model
    def create_new_picking_with_dest(self, picking_type, dest_location):
        """
        Tạo một điều chuyển mới cho picking_type đã cho với vị trí đích là dest_location.
        
        :param picking_type: Bản ghi của stock.picking.type
        :param dest_location: Bản ghi của stock.location (vị trí đích)
        :return: Bản ghi của điều chuyển mới được tạo
        """
        # Lấy vị trí nguồn mặc định từ warehouse của picking_type
        default_dest, default_src = picking_type.warehouse_id._get_partner_locations()
        if picking_type.default_location_src_id:
            default_src = picking_type.default_location_src_id

        # Sử dụng dest_location nếu có, nếu không thì dùng default_location_dest_id hoặc default_dest
        new_dest = dest_location or picking_type.default_location_dest_id or default_dest

        new_picking = self.env['stock.picking'].create({
            'user_id': False,
            'picking_type_id': picking_type.id,
            'location_id': default_src.id,
            'location_dest_id': new_dest.id,
        })
        return new_picking
    
    @api.model
    def filter_base_on_barcode(self, barcode):
        """
        Khi quét barcode:
        - Nếu barcode khớp với một bản ghi của stock.location thì tạo điều chuyển mới với
            location_dest_id là bản ghi vị trí vừa quét và trả về action kiểu client để mở form tùy chỉnh.
        - Nếu không, tiếp tục xử lý theo logic ban đầu (tìm kiếm theo sản phẩm, kiện, lô).
        """
        # Kiểm tra barcode có khớp với một vị trí trong kho không
        location_rec = self.env['stock.location'].search([('barcode', '=', barcode)], limit=1)
        if location_rec:
            picking_type = self.env['stock.picking.type'].browse(self.env.context.get('active_id'))
            # Tạo mới điều chuyển với hàm create_new_picking_with_dest (đã được định nghĩa riêng)
            new_picking = self.create_new_picking_with_dest(picking_type, location_rec)
            # Trả về action kiểu client với tag custom để JS mở form theo định nghĩa (ví dụ: smartbiz_barcode_stock.stock_picking_client_action)
            return {

                'tag': 'smartbiz_barcode_stock.stock_picking_client_action',
                'params': {
                    'active_id': new_picking.id,
                    'resModel': 'stock.picking',
                },
            }
            
        
        """ Searches ready pickings for the scanned product/package/lot.
        """
        barcode_type = None
        nomenclature = self.env.company.nomenclature_id
        if nomenclature.is_gs1_nomenclature:
            parsed_results = nomenclature.parse_barcode(barcode)
            if parsed_results:
                # filter with the last feasible rule
                for result in parsed_results[::-1]:
                    if result['rule'].type in ('product', 'package', 'lot'):
                        barcode_type = result['rule'].type
                        break

        active_id = self.env.context.get('active_id')
        picking_type = self.env['stock.picking.type'].browse(self.env.context.get('active_id'))
        base_domain = [
            ('picking_type_id', '=', picking_type.id),
            ('state', 'not in', ['cancel', 'done', 'draft'])
        ]

        picking_nums = 0
        additional_context = {'active_id': active_id}
        if barcode_type == 'product' or not barcode_type:
            product = self.env['product.product'].search([('barcode', '=', barcode)], limit=1)
            if product:
                picking_nums = self.search_count(base_domain + [('product_id', '=', product.id)])
                additional_context['search_default_product_id'] = product.id
        if self.env.user.has_group('stock.group_tracking_lot') and (barcode_type == 'package' or (not barcode_type and not picking_nums)):
            package = self.env['stock.quant.package'].search([('name', '=', barcode)], limit=1)
            if package:
                pack_domain = ['|', ('move_line_ids.package_id', '=', package.id), ('move_line_ids.result_package_id', '=', package.id)]
                picking_nums = self.search_count(base_domain + pack_domain)
                additional_context['search_default_move_line_ids'] = barcode
        if self.env.user.has_group('stock.group_production_lot') and (barcode_type == 'lot' or (not barcode_type and not picking_nums)):
            lot = self.env['stock.lot'].search([
                ('name', '=', barcode),
                ('company_id', '=', picking_type.company_id.id),
            ], limit=1)
            if lot:
                lot_domain = [('move_line_ids.lot_id', '=', lot.id)]
                picking_nums = self.search_count(base_domain + lot_domain)
                additional_context['search_default_lot_id'] = lot.id
        if not barcode_type and not picking_nums:  # Nothing found yet, try to find picking by name.
            picking_nums = self.search_count(base_domain + [('name', '=', barcode)])
            additional_context['search_default_name'] = barcode

        if not picking_nums:
            if barcode_type:
                return {
                    'warning': {
                        'message': _("No %(picking_type)s ready for this %(barcode_type)s", picking_type=picking_type.name, barcode_type=barcode_type),
                    }
                }
            return {
                'warning': {
                    'title': _('No product, lot or package found for barcode %s', barcode),
                    'message': _('Scan a product, a lot/serial number or a package to filter the transfers.'),
                }
            }

        action = picking_type.open_picking_kanban()
        action['context'].update(additional_context)
        return {'action': action}

    @api.model
    def open_new_picking_barcode(self):
        """ Creates a new picking of the current picking type and open it.

        :return: the action used to open the picking, or false
        :rtype: dict
        """
        context = self.env.context
        if context.get('active_model') == 'stock.picking.type':
            picking_type = self.env['stock.picking.type'].browse(context.get('active_id'))
            if picking_type.exists():
                new_picking = self.create_new_picking(picking_type)
                return new_picking.id
        return False

    @api.model
    def create_new_picking(self, picking_type):
        """ Create a new picking for the given picking type.

        :param picking_type:
        :type picking_type: :class:`~odoo.addons.stock.models.stock_picking.PickingType`
        :return: a new picking
        :rtype: :class:`~odoo.addons.stock.models.stock_picking.Picking`
        """
        # Find source and destination Locations
        location_dest_id, location_id = picking_type.warehouse_id._get_partner_locations()
        if picking_type.default_location_src_id:
            location_id = picking_type.default_location_src_id
        if picking_type.default_location_dest_id:
            location_dest_id = picking_type.default_location_dest_id

        # Create and confirm the picking
        return self.env['stock.picking'].create({
            'user_id': False,
            'picking_type_id': picking_type.id,
            'location_id': location_id.id,
            'location_dest_id': location_dest_id.id,
        })

    def open_new_batch_picking_barcode(self):
        picking_batch = self.env['stock.picking.batch'].create({})
        return picking_batch.id

    def update_batch_picking(self,picking_id,values,batch_id):
        batch_id = self.env['stock.picking.batch'].browse(batch_id)
        batch_id.write(values)
        return self.get_data(picking_id,batch_id.id)

    def button_validate(self):
        for pk in self:
            self.update_picking_data(pk.move_ids)
        return super().button_validate()

    def update_picking_data(self,moves):
        for move in moves:
            origin = move.picking_id.origin
            data = {}
            move_dests = move.move_dest_ids
            for m in move_dests:
                if origin != m.picking_id.origin and origin:
                    data['origin'] = origin
                m.picking_id.write(data)
                self.update_picking_data(move_dests)
                break
            break
            
    def check_package_location(self, package_id, location_id):
        location = self.env['stock.location'].browse(location_id)
        package = self.env['stock.quant.package'].browse(package_id)
        package_location = package.location_id

        if package_location and package_location.id == location.id:
            return True
        elif package_location and package_location.parent_path:
            # Check if the package's location is a child of the given location
            parent_location_ids = [int(loc_id) for loc_id in package_location.parent_path.strip('/').split('/')]
            if location.id in parent_location_ids:
                return True
        return False

    def get_barcode_data(self,barcode,filters,barcodeType):
        if barcodeType:
            if barcodeType == 'lots':
                record = self.env['stock.lot'].search_read([('name','=',barcode),('product_id','=',filters['product_id'])],limit=1,
                                                           fields=self._get_fields('stock.lot'))
            elif barcodeType == 'products':
                record = self.env['product.product'].search_read([('barcode','=',barcode)],limit=1,
                                                           fields=self._get_fields('product.product'))
            elif barcodeType == 'locations':
                record = self.env['stock.location'].search_read([('barcode','=',barcode)],limit=1,
                                                           fields=self._get_fields('stock.location'))
            elif barcodeType == 'packages':
                record = self.env['stock.quant.package'].search([('name','=',barcode)],limit=1)
                if record:
                    prods = []
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
                        prods.append(
                            {'product_id': product_id, 'location_id': location_id, 'quantity': quantity, 'lot_id': lot_id,'lot_name': lot_name,'product_uom_id':product_uom_id,'location_name':location_name,'available_quantity':available_quantity,'expiration_date':expiration_date})
                    record = [{'id': record.id, 'name': record.name, 'location': record.location_id.id,'location_name': record.location_id.display_name, 'products': prods}]
            if record:
                return {'barcode':barcode,'match':True,'barcodeType':barcodeType,'record':record[0],'fromCache':False}
        else:
            if filters:
                record = self.env['stock.lot'].search([('name', '=', barcode), ('product_id', '=', filters['product_id'])],
                                                 limit=1)
            else:
                record = self.env['stock.lot'].search([('name', '=', barcode)], limit=1)

            if record:
                data = {
                    'name': record.name,
                    'ref': record.ref,
                    'product_id': record.product_id.id if record.product_id else False,
                    'expiration_date': record.expiration_date,
                    'create_date': record.create_date,
                    'product_qty': record.product_qty,
                    'id': record.id,
                    'display_name': record.display_name,
                    'product_name': record.product_id.name if record.product_id else '',
                    'product_uom_id': record.product_id.uom_id.id if record.product_id else False,
                    'location_id': record.location_id.id if record.location_id else False,
                }
                return {'barcode':barcode,'match':True,'barcodeType':'lots','record':data,'fromCache':False}
            record = self.env['product.product'].search_read([('barcode', '=', barcode)], limit=1,
                                                           fields=self._get_fields('product.product'))
            if record:
                return {'barcode': barcode, 'match': True, 'barcodeType': 'products', 'record': record[0],'fromCache':False}

            record = self.env['stock.location'].search_read([('barcode', '=', barcode)], limit=1,
                                                           fields=self._get_fields('stock.location'))
            if record:
                return {'barcode': barcode, 'match': True, 'barcodeType': 'locations', 'record': record[0],'fromCache':False}

            record = self.env['stock.quant.package'].search([('name', '=', barcode)], limit=1)
            if record:
                prods = []
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
                    prods.append(
                        {'product_id': product_id, 'location_id': location_id, 'quantity': quantity, 'lot_id': lot_id,'lot_name': lot_name,'product_uom_id':product_uom_id,'location_name':location_name,'available_quantity':available_quantity,'expiration_date':expiration_date})
                record = {'id': record.id, 'name': record.name, 'location': record.location_id.id, 'location_name': record.location_id.display_name,'products': prods}
                return {'barcode': barcode, 'match': True, 'barcodeType': 'packages', 'record': record,'fromCache':False}
        return {'barcode': barcode, 'match': False, 'barcodeType': barcodeType, 'record': False,'fromCache':False}

    def _get_fields(self,model):
        if model == 'mrp.production':
            return ['name','state','product_id','product_uom_id','product_uom_qty','qty_produced','qty_producing','date_start','date_deadline','date_finished','company_id']
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
            return ['name','location_id','quant_ids']
        if model == 'stock.lot':
            return ['name', 'ref', 'product_id','expiration_date','create_date','product_qty']
        if model == 'uom.uom':
            return ['name','category_id','factor','rounding',]
        if model == 'stock.quant':
            return ['product_id','location_id','inventory_date','inventory_quantity','inventory_quantity_set','quantity','product_uom_id','lot_id','package_id','owner_id','inventory_diff_quantity','user_id',]
        return []
    def unpacked_move_lines(self,picking_id):
        picking = self.search([['id','=',picking_id]],limit=1)
        moves = picking.move_ids        
        unpacked_move_lines = moves.move_line_ids.filtered(lambda ml: not ml.result_package_id)
        return unpacked_move_lines.read(self._get_fields('stock.move.line'))
    
    def get_data(self,picking_id,batch_id=False):
        if batch_id:
            batch_id = self.env['stock.picking.batch'].browse(batch_id)
            picking = batch_id.picking_ids
        else:
            picking = self.search([['id','=',picking_id]],limit=1)
        moves = picking.move_ids        
        products = moves.product_id      
        uoms = moves.product_uom      
        move_lines = moves.move_line_ids
        packages = move_lines.package_id | move_lines.result_package_id
        #lots = move_lines.lot_id|self.env['stock.lot'].search( [('company_id', '=', picking.company_id.id), ('product_id', 'in', products.ids)])
        source_locations = self.env['stock.location'].search([('id', 'child_of', picking.location_id.ids)])
        destination_locations = self.env['stock.location'].search([('id', 'child_of', picking.location_dest_id.ids)])
        locations = move_lines.location_id | move_lines.location_dest_id | moves.location_id | moves.location_dest_id  | source_locations |destination_locations
        mls = []
        mvs = []
        for ml in move_lines:
            mls.append({
            'id':ml.id,
            'move_id':ml.move_id.id,
            'picking_id': ml.picking_id.id,
            'picking_name': ml.picking_id.name,
            'picking_type_code': ml.picking_id.picking_type_id.code or '',
            'state': ml.state,
            'date': ml.date,
            'product_id' :ml.product_id.id,
            'product_name' :ml.product_id.display_name or '',
            'product_barcode': ml.product_id.barcode or '',
            'product_tracking': ml.product_id.tracking,
            'product_uom': ml.product_id.uom_id.name or '',
            'product_uom_id': ml.product_id.uom_id.id,
            'quantity': round(ml.quantity,2),
            'lot_id':ml.lot_id.id,
            'lot_name':ml.lot_name or ml.lot_id.name,
            'expiration_date':ml.lot_id.expiration_date,
            'location_id':ml.location_id.id,
            'location_name':ml.location_id.display_name or '',
            'location_barcode':ml.location_id.barcode or '',
            'location_dest_id':ml.location_dest_id.id,
            'location_dest_name':ml.location_dest_id.display_name or '',
            'location_dest_barcode':ml.location_dest_id.barcode or '',
            'result_package_id':ml.result_package_id.id,
            'result_package_name':ml.result_package_id.name or '',
            'package_id':ml.package_id.id,
            'package_name':ml.package_id.name or '',
            'picked':ml.picked or False,
            'batch_picking_type_id': batch_id.picking_type_id.id if batch_id else False
        })
        for mv in moves:
            picked = all(line.picked for line in mv.move_line_ids)
            mvs.append({
            'id':mv.id,
            'picking_id': mv.picking_id.id,
            'picking_name': mv.picking_id.name,
            'picking_type_code': mv.picking_id.picking_type_id.code or '',
            'state': mv.state,
            'date': mv.date,
            'product_id' :mv.product_id.id,
            'product_name' :mv.product_id.display_name or '',
            'product_name_' :mv.product_id.name or '',
            'product_code' :mv.product_id.default_code or '',
            'product_barcode': mv.product_id.barcode or '',
            'product_tracking': mv.product_id.tracking,
            'product_uom': mv.product_id.uom_id.name or '',
            'product_uom_id': mv.product_id.uom_id.id,
            'product_uom_qty':round(mv.product_uom_qty,2),
            'quantity': round(mv.quantity,2),
            'product_qty':round(mv.product_qty),
            'lot_id': False,
            'lot_name':mv.picking_id.lot,
            'location_id':mv.location_id.id,
            'location_name':mv.location_id.display_name or '',
            'location_barcode':mv.location_id.barcode or '',
            'location_dest_id':mv.location_dest_id.id,
            'location_dest_name':mv.location_dest_id.display_name or '',
            'location_dest_barcode':mv.location_dest_id.barcode or '',
            'picked': mv.picked or False,
            'all_lines_picked':picked,
            'lot_name':mv.picking_id.lot or '',

        })
        
        pkg_data = {}
        for ml in moves.move_line_ids.filtered(lambda ml: ml.result_package_id):
            pkg_id = ml.result_package_id.id
            pkg_name = ml.result_package_id.name or ''
            prod_id = ml.product_id.id
            product_uom = ml.product_id.uom_id.name
            product_uom_id = ml.product_id.uom_id.id
            prod_name = ml.product_id.display_name or ''
            product_uom_qty = ml.move_id.product_uom_qty
            qty = ml.quantity
            remain_qty = product_uom_qty - qty

            # Nếu package chưa tồn tại trong pkg_data, khởi tạo
            if pkg_id not in pkg_data:
                pkg_data[pkg_id] = {
                    'name': pkg_name,
                    'package_id': pkg_id,
                    'products': {},
                    'lines': []  # Khởi tạo danh sách lines rỗng
                }
            
            # Tính toán thông tin sản phẩm trong package
            if prod_id not in pkg_data[pkg_id]['products']:
                pkg_data[pkg_id]['products'][prod_id] = {
                    'id': prod_id,
                    'product_name': prod_name,
                    'product_uom': product_uom,
                    'product_uom_id':product_uom_id,
                    'quantity': 0,
                    'product_uom_qty': product_uom_qty,
                    'remain_qty': remain_qty
                }
            pkg_data[pkg_id]['products'][prod_id]['quantity'] += qty

            # Thêm thông tin move line vào danh sách lines của package
            line_data = ml.read(self._get_fields('stock.move.line'))
            pkg_data[pkg_id]['lines'].append(line_data[0])

        # Tạo danh sách finish_packages với cả thông tin products và lines
        finish_packages = []
        for pkg in pkg_data.values():
            product_list = []
            for prod in pkg['products'].values():
                product_list.append(prod)
            finish_packages.append({
                'name': pkg['name'],
                'id': pkg['package_id'],
                'products': product_list,
                'lines': pkg['lines'],  # Bổ sung thông tin các move line cho package
            })
        
        unpacked_products = []
        for mv in moves:
            total_finished_qty = mv.product_uom_qty or 0.0
            # Hoặc có thể xài move.quantity (tuỳ code cũ)
            
            # Tính tổng quantity đã được đóng gói (có result_package_id)
            packed_lines = mv.move_line_ids.filtered(lambda ml: ml.result_package_id)
            
            total_packed_qty = sum(packed_lines.mapped('quantity'))

            available_qty = total_finished_qty - total_packed_qty
            if available_qty > 0:
                # Gom thông tin cho form "đóng gói"
                # Gắn kèm move_id, product tracking, location... tuỳ ý
                product_data = {
                    'move_id': mv.id,
                    'product_id': mv.product_id.id,
                    'product_name': mv.product_id.display_name or '',
                    'product_tracking': mv.product_id.tracking,
                    'location_id': mv.location_id.id,
                    'location_dest_id': mv.location_dest_id.id,
                    'available_quantity': available_qty,
                    # Tuỳ logic: 
                    #   - Mặc định 'qtyPerPackage' = 0 (người dùng sẽ nhập)
                    #   - 'packageCount' = 0 
                }
                unpacked_products.append(product_data)

        # Lấy thông tin các kiện hàng
        packs = []
        for pack in packages:
            prods = []
            for quant in pack.quant_ids:
                product_id = quant.product_id.id
                product_uom_id = quant.product_id.uom_id.id
                location_id = quant.location_id.id
                location_name = quant.location_id.display_name
                quantity = quant.quantity
                available_quantity = quant.available_quantity
                lot_id = quant.lot_id.id
                prods.append({'product_id':product_id,'location_id':location_id,'quantity':quantity,'lot_id':lot_id,'product_uom_id':product_uom_id,'location_name':location_name,'available_quantity':available_quantity})
            packs.append({'id':pack.id,'name':pack.name,'location':pack.location_id.id,'products':prods})
        data = {           
            'moves': mvs,         
            'move_lines': mls,
            'packages': packs,
            #'lots': lots.read(picking._get_fields('stock.lot')),
            'locations': locations.read(picking._get_fields('stock.location')),
            'products': products.read(picking._get_fields('product.product')),
            'uoms':uoms.read(picking._get_fields('uom.uom')),
            'company_id': picking.company_id.id if not batch_id else picking[0].company_id.id if picking else False,
            'partner_id':picking.partner_id.id if not batch_id else picking[0].partner_id.id if picking else False,
            'partner_name':picking.partner_id.name if not batch_id else picking[0].partner_id.name if picking else '',
            'user_id':picking.user_id.id if not batch_id else picking[0].user_id.id if picking else False,
            'user_name': picking.user_id.name or '' if not batch_id else picking[0].user_id.name or '' if picking else '',
            'lot_name': picking.lot or '' if not batch_id else picking[0].lot or '' if picking else '',
            'location_id':picking.location_id.id if not batch_id else picking[0].location_id.id if picking else False,
            'location_name':picking.location_id.display_name or '' if not batch_id else picking[0].location_id.display_name or '' if picking else '',
            'location_dest_id': picking.location_dest_id.id if not batch_id else picking[0].location_dest_id.id if picking else False,
            'location_dest_name': picking.location_dest_id.display_name or '' if not batch_id else picking[0].location_dest_id.display_name or '' if picking else '',
            'picking_type_code': batch_id.picking_type_id.code if batch_id else picking.picking_type_id.code,
            'state_name': self.sel_display(batch_id or picking, 'state'),
            'state':(batch_id or picking).state,
            'name': batch_id.name if batch_id else picking.name,
            'origin': batch_id.origin if batch_id else picking.origin,
            'scheduled_date': str(batch_id.scheduled_date) if batch_id else str(picking.scheduled_date),
            'order':[{'lot_name':picking.lot or '' if not batch_id else picking[0].lot or '' if picking else '',}],
            'finish_packages': finish_packages,
            'unpacked_moves':unpacked_products,
            
        }
        return data
    
    def check_serial_number(self, serial_id):
        onhand = self.env['stock.quant'].search([('lot_id', '=', serial_id),('location_id.usage','=','internal')], limit=1)
        if onhand and onhand.quantity > 0:
            return True
        else:
            return False
       
    def sel_display(self, record, field_name):
        """
        Trả về nhãn hiển thị (đã dịch) của một trường Selection bất kể version.
        - record : môi trường bản ghi (stock.picking, mrp.batch, …)
        - field  : tên trường selection (str), ví dụ 'state'
        """
        value = record[field_name]
           # Không phải selection thì trả mã kỹ thuật

        # id của trường trong ir.model.fields
        field_id = record.env['ir.model.fields']._get(
            record._name, field_name
        ).id

        # Tra nhãn
        sel_rec = record.env['ir.model.fields.selection'].sudo().search([
            ('field_id', '=', field_id),
            ('value', '=', value),
        ], limit=1)
        if sel_rec:
            return sel_rec.name
        else:
            return value

    def create_move(self,picking_id,values,batch_id=False):
        move = self.env['stock.move'].create(values)
        data = self.get_data(picking_id,batch_id)
        return {'move_id':move.id,'data':data}

    def save_data(self,picking_id,data,batch_id=False):
        picking = self.env['stock.picking'].browse(picking_id)
        if picking.state == 'draft':
            picking.action_confirm()
        quantity = float(data['quantity'])
        package_id = data['package_id'] if 'package_id' in data.keys() else False
        result_package_id = data['result_package_id'] if 'result_package_id' in data.keys()  else False
        # if package_id == result_package_id:
            # lines = self.env['stock.move.line'].search([('picked','=',True),('package_id','=',package_id),('picking_id','!=',picking_id),('state','not in',['done','cancel'])])
            # if lines:
                # Picking = ', '.join(line.picking_id.name or 'Unknown' for line in lines) 
                # raise ValidationError(_("Kiện hàng '%s' đã có trong đơn hàng '%s'. Vui lòng kiểm tra lại.") % (data['package_name'],Picking))

        if not data['lot_id'] and data['lot_name']:
            lot_id = self.env['stock.lot'].search([('name','=',data['lot_name']),(['product_id','=',data['product_id']])],limit=1)
            if lot_id:
                data['lot_id'] = lot_id.id
            else:
                data['lot_id'] = self.env['stock.lot'].create({'name':data['lot_name'],'product_id':data['product_id']}).id

        update = {'quantity': quantity, 'location_id': data['location_id'],
             'location_dest_id': data['location_dest_id'], 'lot_id': data['lot_id'],'lot_name': data['lot_name'],
             'package_id':package_id,'result_package_id':result_package_id,'picked':True}
        create = { 'product_id': data['product_id'], 'product_uom_id': data['product_uom_id'],
             'quantity': quantity, 'location_id': data['location_id'],'picking_id':data['picking_id'],
             'location_dest_id': data['location_dest_id'], 'lot_id': data['lot_id'], 'lot_name': data['lot_name'],
             'package_id':package_id,'result_package_id':result_package_id,'picked':True}

        if data['id']:
            self.env['stock.move.line'].browse(data['id']).write(update)
        else:
            self.env['stock.move.line'].create(create)
        return self.get_data(picking_id,batch_id)

    def create_pack(self,picking_id,data,package_name,batch_id=False):
        if package_name:
            package = self.env['stock.quant.package'].search([('name','=',package_name)],limit=1)
            if package:
                package_id = package.id
            else:
                package_id = self.env['stock.quant.package'].create({'name':package_name})
        else:
            package_id = self.env['stock.quant.package'].create({})

        data['result_package_id'] = package_id.id
        return self.save_data(picking_id,data,batch_id)
        
    def create_package(self,package_name):
        if package_name:
            package = self.env['stock.quant.package'].search([('name','=',package_name)],limit=1)
            if package:
                package_id = package
                package_name = package.name
            else:
                package_id = self.env['stock.quant.package'].create({'name':package_name})
                
        else:
            package_id = self.env['stock.quant.package'].create({})
            package_name = package_id.name
            

        return {'id':package_id.id,'name':package_name}

    def update_package(self,picking_id,batch_id,lines):
        for l in lines:  
            line = self.env['stock.move.line'].browse(l['id'])
            qty = float(l['quantity'])
            #raise UserError(_("line %s" % line ))
            if qty <= 0:
                line.write({'result_package_id':False})
            else:
                line.write({'result_package_id':l['result_package_id'],'quantity':qty})
            
        return self.get_data(picking_id,batch_id)
   
    def create_packages(self, picking_id, batch_id, lines):
        vals_list = []
        for data in lines:
            product = self.env['product.product'].browse(data['product_id'])
            lot_id = data.get('lot_id') or False
            if not lot_id and data.get('lot_name'):
                lot = self.env['stock.lot'].search([
                    ('name', '=', data['lot_name']),
                    ('product_id', '=', data['product_id'])
                ], limit=1)
                if not lot:
                    lot = self.env['stock.lot'].create({
                        'name': data['lot_name'], 'product_id': data['product_id']
                    })
                lot_id = lot.id

            vals_list.append({
                'move_id': data['move_id'],
                'product_id': data['product_id'],
                'product_uom_id': product.uom_id.id,
                'quantity': data['quantity'],
                'location_id': data['location_id'],
                'location_dest_id': data['location_dest_id'],
                'lot_id': lot_id,
                'package_id': data['package_id'],
                'result_package_id': data['result_package_id'],
                'state': 'assigned',
                'picked': True,
            })
        if vals_list:
            self.env['stock.move.line'].create(vals_list)
        return self.get_data(picking_id, batch_id)

    def save_lines_bulk(self, picking_id, lines, batch_id=False):
        # Tắt prefetch để giảm overhead trong batch lớn
        self = self.with_context(prefetch_fields=False)

        picking = self.browse(picking_id)
        if picking.state == 'draft':
            picking.action_confirm()  # Xác nhận 1 lần cho cả batch

        # 1) Thu thập các (product_id, lot_name) cần resolve theo lô
        to_resolve = {}
        product_ids = set()
        for d in lines:
            if not d.get('lot_id') and d.get('lot_name'):
                to_resolve.setdefault(d['product_id'], set()).add(d['lot_name'])
            product_ids.add(d['product_id'])

        # 2) Tìm lot theo batch, thiếu thì tạo hàng loạt
        lot_map = {}
        if to_resolve:
            all_names = set()
            for names in to_resolve.values():
                all_names |= names
            lots = self.env['stock.lot'].search([
                ('name', 'in', list(all_names)),
                ('product_id', 'in', list(product_ids)),
            ])
            for l in lots:
                lot_map[(l.product_id.id, l.name)] = l.id

            to_create = []
            for pid, names in to_resolve.items():
                for nm in names:
                    if (pid, nm) not in lot_map:
                        to_create.append({'name': nm, 'product_id': pid})
            if to_create:
                new_lots = self.env['stock.lot'].create(to_create)  # bulk create
                for l in new_lots:
                    lot_map[(l.product_id.id, l.name)] = l.id

        # 3) Chuẩn bị create/write theo batch
        create_vals = []
        to_write = []  # (id, vals)
        for d in lines:
            lot_id = d.get('lot_id')
            if not lot_id and d.get('lot_name'):
                lot_id = lot_map.get((d['product_id'], d['lot_name']))

            common = {
                'quantity': float(d.get('quantity') or 0.0),           # chỉ dùng quantity
                'location_id': d['location_id'],
                'location_dest_id': d['location_dest_id'],
                'lot_id': lot_id,
                'lot_name': d.get('lot_name') or False,
                'package_id': d.get('package_id') or False,
                'result_package_id': d.get('result_package_id') or False,
                'picked': True,
            }

            if d.get('id'):
                to_write.append((d['id'], common))
            else:
                vals = dict(common,
                    product_id=d['product_id'],
                    product_uom_id=d['product_uom_id'],
                    picking_id=picking_id,
                )
                create_vals.append(vals)

        # 4) Thực thi
        if create_vals:
            self.env['stock.move.line'].create(create_vals)  # bulk create dòng mới

        for rec_id, vals in to_write:                        # write các dòng cũ
            self.env['stock.move.line'].browse(rec_id).write(vals)

        # 5) Trả dữ liệu (giữ nguyên hành vi cũ để frontend không phải đổi nhiều)
        return self.get_data(picking_id, batch_id)

    def delete_move_line(self,picking_id,move_line_id,batch_id=False):
        self.env['stock.move.line'].browse(move_line_id).unlink()
        return self.get_data(picking_id,batch_id)

    def delete_move(self,picking_id,move_id,batch_id=False):
        self.env['stock.move'].browse(move_id).unlink()
        return self.get_data(picking_id,batch_id)

    def done_move_line(self,picking_id,move_line_id,batch_id=False):
        self.env['stock.move.line'].browse(move_line_id)._action_done()
        return self.get_data(picking_id,batch_id)

    def done_move(self,picking_id,move_id,batch_id=False):
        self.env['stock.move'].browse(move_id)._action_done()
        return self.get_data(picking_id,batch_id)

    def barcode_action_done(self, picking_id, batch_id=False):
        # Lấy context hiện tại từ env

        current_context = self.env.context

        if batch_id:
            # Sử dụng context hiện tại với hàm action_done
            batch = self.env['stock.picking.batch'].browse(batch_id).with_context(**current_context)
            e = []
            for line in batch.move_line_ids:
                package_id = line.package_id  
                result_package_id = line.result_package_id
                product_id = line.product_id  # Lấy sản phẩm từ line
                if package_id.id == result_package_id.id and package_id and result_package_id:
                    lines = self.env['stock.move.line'].search([('picked','=',True),('package_id','=',package_id.id),('state','not in',['done','cancel'])])
                    if lines:
                        # Tính tổng số lượng trong stock.move.line cho sản phẩm cụ thể
                        total_qty_lines = sum(lines.mapped('quantity'))

                        # Tính tổng số lượng trong stock.quant cho package và sản phẩm cụ thể
                        total_qty_package = sum(self.env['stock.quant'].search([
                            ('package_id', '=', package_id.id),
                            #('product_id', '=', product_id.id)
                        ]).mapped('quantity'))

                        # Kiểm tra sự khác biệt giữa tổng số lượng
                        if total_qty_lines != total_qty_package:
                            Picking = ', '.join(line.picking_id.name or 'Unknown' for line in lines)
                            e.append(("Kiện hàng '%s' với sản phẩm '%s' đã có trong đơn hàng '%s'. Vui lòng kiểm tra lại.") 
                                  % (package_id.name, product_id.name, Picking))
            # Kiểm tra xem danh sách e có rỗng hay không
            if e:
                raise ValidationError('\n'.join(e))
            res = batch.action_done()
        else:
            # Sử dụng context hiện tại với hàm button_validate
            picking = self.browse(picking_id).with_context(**current_context)
            e = []
            for line in picking.move_line_ids:
                package_id = line.package_id  
                result_package_id = line.result_package_id
                product_id = line.product_id  # Lấy sản phẩm từ line
                if package_id.id == result_package_id.id and package_id and result_package_id:
                    lines = self.env['stock.move.line'].search([('picked','=',True),('package_id','=',package_id.id),('state','not in',['done','cancel'])])
                    if lines:
                        # Tính tổng số lượng trong stock.move.line cho sản phẩm cụ thể
                        total_qty_lines = sum(lines.mapped('quantity'))

                        # Tính tổng số lượng trong stock.quant cho package và sản phẩm cụ thể
                        total_qty_package = sum(self.env['stock.quant'].search([
                            ('package_id', '=', package_id.id),
                            #('product_id', '=', product_id.id)
                        ]).mapped('quantity'))

                        # Kiểm tra sự khác biệt giữa tổng số lượng
                        if total_qty_lines != total_qty_package:
                            Picking = ', '.join(line.picking_id.name or 'Unknown' for line in lines)
                            e.append(("Kiện hàng '%s' với sản phẩm '%s' đã có trong đơn hàng '%s'. Vui lòng kiểm tra lại.") 
                                  % (package_id.name, product_id.name, Picking))
            for line in picking.move_line_ids:
                package_id = line.package_id  
                result_package_id = line.result_package_id
                if result_package_id:
                    lines = self.env['stock.move.line'].search([('package_id','=',result_package_id.id),('picking_id','!=',picking_id),('location_id','!=',line.location_dest_id.id),('state','not in',['done','cancel'])])
                    if lines:
                        Picking = ', '.join(line.picking_id.name or 'Unknown' for line in lines) 
                        e.append(("Kiện hàng '%s' đã được đóng trong đơn hàng '%s'. Vui lòng kiểm tra lại.") % (result_package_id.name,Picking))
            # Kiểm tra xem danh sách e có rỗng hay không
            if e:
                raise ValidationError('\n'.join(e))
            res = picking.button_validate()

        # Kiểm tra nếu res là một dictionary và có key 'type'
        if isinstance(res, dict) and 'type' in res and res['type'] == 'ir.actions.act_window':
            return {'action': res}
        return self.get_data(picking_id, batch_id)
    
    def cancel_order(self, picking_id, batch_id=False):
        if batch_id:
            batch = self.env['stock.picking.batch'].browse(batch_id)
            res = batch.action_cancel()
        else:
            picking = self.browse(picking_id)
            res = picking.action_cancel()

        return self.get_data(picking_id, batch_id)

    def print_line(self,move_line_id,label=False):
        line = self.env['stock.move.line'].browse(move_line_id)
        return line.print_label()

    def check_package(self,package_id):
        package = self.env['stock.quant.package'].browse(package_id)     
        lines = self.env['stock.move.line'].search([('package_id','=',package_id),('state','not in',['done','cancel'])])
        if lines:
            Picking = ', '.join(line.picking_id.name or 'Unknown' for line in lines) 
            raise ValidationError(("Kiện hàng '%s' đã được dự trữ hết trong các lệnh '%s'. Vui lòng kiểm tra lại.") % (package.name,Picking))
        
class Stock_PickingBatch(models.Model):
    _inherit = ['stock.picking.batch']
    name = fields.Char(store='True')

class StockQuant(models.Model):
    _inherit = ['stock.quant']
    
    @api.model
    def get_inventory_data(self):
        current_user = self.env.user
        
        inventory_data = self.sudo().search_read([["quantity", ">", 0],["location_id.usage", "=", "internal"],["user_id", "=", current_user.id]], ['product_id', 'quantity', 'location_id', 'inventory_quantity', 'package_id', 'lot_id', 'user_id'])
        # inventory_data = self.env['stock.quant'].sudo().search([])
        return [{
            'id': record['id'],
            'product_name': record['product_id'][1] if record['product_id'] else 'Unknown',
            'quantity': record['quantity'],
            'inventory_quantity': record['inventory_quantity'],
            'location_name': record['location_id'][1] if record['location_id'] else 'Unknown',
            'location_id': record['location_id'],
            'package_id': record['package_id'],
            'package_name': record['package_id'][1] if record['package_id'] else False,
            'lot_id': record['lot_id'],
            'lot_name': record['lot_id'][1] if record['lot_id'] else False,
            'user_id': record['user_id'],
        } for record in inventory_data]
        
        
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

class stock_moveline(models.Model):
    _inherit = ['stock.move.line']
    product_id = fields.Many2one('product.product', store='True')


    def print_label(self,label_name = False,printer_name = False):
        self = self.sudo()
        domain = [('model_id.model','=',self._name)]
        if label_name:
            domain.append(('name','=',label_name))
        printer = self.env.user.printing_printer_id or self.env['printing.printer'].search([('name','like',printer_name)],limit=1)
        label = self.env['printing.label.zpl2'].search(domain,limit=1)  
        if label and printer:
            for record in self:         
                label.print_label(printer, record)    
        return {'printer':printer.name,'label':label.name,'domain':domain}