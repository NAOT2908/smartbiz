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


class mrp_Production(models.Model):
    _inherit = ['mrp.production']
    production_line_id = fields.Many2one('smartbiz_mes.production_line', string='Production Line')
    name = fields.Char(store='True', readonly=False)

    def open_mrp_kanban(self):
        """ Mở Kanban view cho MRP Production """
        view_id = self.env.ref('smartbiz_barcode_production.mrp_production_kanban').id  # Đổi module nếu cần
        context = {
            'search_default_state': ['confirmed', 'progress'],  # Lọc trạng thái đơn sản xuất đang chạy
            'search_default_product_id': self.product_id.id if self.product_id else False,
            'default_product_id': self.product_id.id if self.product_id else False,
            'default_company_id': self.company_id.id,
            'search_default_workcenter_id': self.workcenter_id.id if self.workcenter_id else False,
            'search_default_production_line_id': self.production_line_id.id if self.production_line_id else False,
        }
        
        action = {
            'type': 'ir.actions.act_window',
            'views': [(view_id, 'kanban')],
            'name': _("Manufacturing Orders"),
            'res_model': 'mrp.production',
            'target': 'current',
            'context': context
        }
        return action
    def get_barcode_data(self, barcode, filters, barcodeType):
        # Khởi tạo biến record là None để tránh lỗi truy cập khi chưa gán giá trị
        record = None

        # Kiểm tra xem có barcodeType không
        if barcodeType:
            if barcodeType == 'lots':
                record = self.env['stock.lot'].search_read(
                    [('name', '=', barcode), ('product_id', '=', filters.get('product_id'))],
                    limit=1, fields=self._get_fields('stock.lot')
                )
            elif barcodeType == 'products':
                record = self.env['product.product'].search_read(
                    [('barcode', '=', barcode)],
                    limit=1, fields=self._get_fields('product.product')
                )
            elif barcodeType == 'locations':
                record = self.env['stock.location'].search_read(
                    [('barcode', '=', barcode)],
                    limit=1, fields=self._get_fields('stock.location')
                )
            elif barcodeType == 'packages':
                record = self.env['stock.quant.package'].search([('name', '=', barcode)], limit=1)
                if record:
                    # Xử lý các quant liên quan đến package
                    prods = []
                    for quant in record.quant_ids:
                        prods.append({
                            'product_id': quant.product_id.id,
                            'product_name': quant.product_id.display_name,
                            'location_id': quant.location_id.id,
                            'quantity': quant.quantity,
                            'lot_id': quant.lot_id.id,
                            'lot_name': quant.lot_id.name,
                            'product_uom_id': quant.product_uom_id.id,
                            'product_uom': quant.product_uom_id.name,
                            'location_name': quant.location_id.display_name,
                            'available_quantity': quant.available_quantity,
                            'expiration_date': quant.lot_id.expiration_date,
                        })
                    record = [{
                        'id': record.id,
                        'name': record.name,
                        'location': record.location_id.id,
                        'location_name': record.location_id.display_name,
                        'products': prods
                    }]
        
        # Nếu barcodeType không được chỉ định, tìm kiếm mặc định theo filters và barcode
        if not record:
            if filters:
                record = self.env['stock.lot'].search_read(
                    [('name', '=', barcode), ('product_id', '=', filters.get('product_id'))],
                    limit=1, fields=self._get_fields('stock.lot')
                )
                if record:
                    return {'barcode': barcode, 'match': True, 'barcodeType': 'lots', 'record': record[0], 'fromCache': False}

            # Tìm kiếm sản phẩm
            record = self.env['product.product'].search_read(
                [('barcode', '=', barcode)], limit=1, fields=self._get_fields('product.product')
            )
            if record:
                return {'barcode': barcode, 'match': True, 'barcodeType': 'products', 'record': record[0], 'fromCache': False}

            # Tìm kiếm vị trí
            record = self.env['stock.location'].search_read(
                [('barcode', '=', barcode)], limit=1, fields=self._get_fields('stock.location')
            )
            if record:
                return {'barcode': barcode, 'match': True, 'barcodeType': 'locations', 'record': record[0], 'fromCache': False}

            # Tìm kiếm package
            record = self.env['stock.quant.package'].search([('name', '=', barcode)], limit=1)
            if record:
                prods = []
                for quant in record.quant_ids:
                    prods.append({
                        'product_id': quant.product_id.id,
                        'product_name': quant.product_id.display_name,
                        'location_id': quant.location_id.id,
                        'quantity': quant.quantity,
                        'lot_id': quant.lot_id.id,
                        'lot_name': quant.lot_id.name,
                        'product_uom_id': quant.product_uom_id.id,
                        'product_uom': quant.product_uom_id.name,
                        'location_name': quant.location_id.display_name,
                        'available_quantity': quant.available_quantity,
                        'expiration_date': quant.lot_id.expiration_date,
                    })
                record = {
                    'id': record.id,
                    'name': record.name,
                    'location': record.location_id.id,
                    'location_name': record.location_id.display_name,
                    'products': prods
                }
                return {'barcode': barcode, 'match': True, 'barcodeType': 'packages', 'record': record, 'fromCache': False}

        # Nếu không tìm thấy bất kỳ record nào
        return {'barcode': barcode, 'match': False, 'barcodeType': barcodeType, 'record': False, 'fromCache': False}

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
    
    @api.model
    def filter_base_on_barcode(self, barcode):
        """ Tìm kiếm đơn sản xuất dựa trên barcode của sản phẩm, số lot, workcenter hoặc tên đơn. """
        barcode_type = None
        nomenclature = self.env.company.nomenclature_id
        if nomenclature.is_gs1_nomenclature:
            parsed_results = nomenclature.parse_barcode(barcode)
            if parsed_results:
                for result in parsed_results[::-1]:
                    if result['rule'].type in ('product', 'lot', 'workcenter', 'production'):
                        barcode_type = result['rule'].type
                        break

        active_id = self.env.context.get('active_id')
        production_domain = [('state', 'not in', ['done', 'cancel'])]

        production_nums = 0
        additional_context = {'active_id': active_id}

        # Kiểm tra barcode sản phẩm
        if barcode_type == 'product' or not barcode_type:
            product = self.env['product.product'].search([('barcode', '=', barcode)], limit=1)
            if product:
                production_nums = self.search_count(production_domain + [('product_id', '=', product.id)])
                additional_context['search_default_product_id'] = product.id

        # Kiểm tra barcode số lô
        if self.env.user.has_group('stock.group_production_lot') and (barcode_type == 'lot' or (not barcode_type and not production_nums)):
            lot = self.env['stock.lot'].search([('name', '=', barcode)], limit=1)
            if lot:
                lot_domain = [('lot_producing_id', '=', lot.id)]
                production_nums = self.search_count(production_domain + lot_domain)
                additional_context['search_default_lot_id'] = lot.id

        # Kiểm tra barcode workcenter
        if barcode_type == 'workcenter' or (not barcode_type and not production_nums):
            workcenter = self.env['mrp.workcenter'].search([('code', '=', barcode)], limit=1)
            if workcenter:
                production_nums = self.search_count(production_domain + [('workcenter_id', '=', workcenter.id)])
                additional_context['search_default_workcenter_id'] = workcenter.id
        
        # Kiểm tra barcode production
        if barcode_type == 'production' or (not barcode_type and not production_nums):
            production = self.env['smartbiz_mes.production_line'].search([('code', '=', barcode)], limit=1)
            if production:
                production_nums = self.search_count(production_domain + [('production_line_id', '=', production.id)])
                additional_context['search_default_production_line_id'] = production.id

        # Nếu không tìm thấy theo barcode, thử tìm theo tên đơn sản xuất
        if not barcode_type and not production_nums:
            production_nums = self.search_count(production_domain + [('name', '=', barcode)])
            additional_context['search_default_name'] = barcode

        if not production_nums:
            return {
                'warning': {
                    'title': _('No matching production order found'),
                    'message': _('Scan a product, lot, workcenter, or production name to filter the manufacturing orders.'),
                }
            }

        # Mở view Kanban cho MRP Production
        action = self.open_mrp_kanban()
        action['context'] = additional_context
        return {'action': action}
        
    @api.model
    def open_new_production_barcode(self):
        """ Tạo một đơn sản xuất mới và mở nó.

        :return: Action mở đơn sản xuất hoặc False nếu không thành công
        """
        context = self.env.context
        if context.get('active_model') == 'mrp.production':
            new_production = self.create_new_production()
            return new_production.id if new_production else False
        return False
    
    @api.model
    def create_new_production(self):
        """ Tạo đơn sản xuất mới với thông tin mặc định. """
        default_bom = self.env['mrp.bom'].search([], limit=1)
        if not default_bom:
            raise UserError(_("No Bill of Materials found. Please create one before proceeding."))

        new_production = self.create({
            'product_id': default_bom.product_tmpl_id.product_variant_id.id,
            'product_qty': 1.0,
            'bom_id': default_bom.id,
            'workcenter_id': self.env['mrp.workcenter'].search([], limit=1).id,
        })
        return new_production

    