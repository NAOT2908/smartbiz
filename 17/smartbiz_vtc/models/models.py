# -*- coding: utf-8 -*-

from odoo.tools.float_utils import float_compare, float_is_zero, float_round
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


class SmartBiz_Stock_StockReport(models.Model):
    _inherit = ['smartbiz_stock.stock_report']
    from_date = fields.Date(store='True')


    def action_nxt_ton_kho(self):
        file_name = 'Bao cao NXT kho.xlsx'    
        workbook = self.load_excel(file_name)
        worksheet = workbook.active

        from_date = self.from_date
        to_date = self.to_date + timedelta(days=1)

        transaction_data = self._get_stock_data(from_date, to_date)

        detailed_data = []
        for (product_id, lot_id, warehouse_id), data in transaction_data.items():
            product = self.env['product.product'].browse(product_id)
            lot = self.env['stock.lot'].browse(lot_id) if lot_id else False
            warehouse = self.env['stock.warehouse'].browse(warehouse_id) if warehouse_id else False
            lot_values = self._get_values_from_split(lot.name if lot else '', ':', 7)
            product_values = self._get_values_from_split(product.name if product else '', '_', 4)
            warehouse_name = warehouse.name if warehouse else ''
            
            detailed_data.append({
                'warehouse': warehouse_name,
                'ma_hang': lot_values[2],
                'order': lot_values[1],
                'product': product_values[0],
                'color': product_values[1],
                'contents': product_values[0],
                'roll': lot_values[4],
                'size': product_values[2],
                'dvt': product.uom_id.name if product and product.uom_id else '',
                'begin_quantity': data['begin_quantity'],
                'in_purchase': data['in_purchase'],
                'in_production': data['in_production'],
                'in_adjust': data['in_adjust'],
                'in_transfer': data['in_transfer'],
                'in_other': data['in_other'],
                'in_total': data['in_total'],
                'out_production': data['out_production'],
                'out_supplier': data['out_supplier'],
                'out_huy': data['out_huy'],
                'out_adjust': data['out_adjust'],
                'out_transfer': data['out_transfer'],
                'out_other': data['out_other'],
                'out_total': data['out_total'],
                'end_quantity': data['end_quantity'],
            })

        detailed_data = sorted(detailed_data, key=lambda x: x['warehouse'])

        worksheet['A3'] = "Range Date: " + from_date.strftime('%d/%m/%Y') + " - " + to_date.strftime('%d/%m/%Y')

        row = 6
        
        for data in detailed_data:
            keys = list(data.keys())
            # Nếu bạn cần thứ tự cụ thể và đang sử dụng phiên bản Python cũ hơn, bạn có thể muốn sắp xếp các khóa:
            # keys = sorted(data.keys())
            for index, key in enumerate(keys, start=1):
                worksheet.cell(row, index, data[key])
            row += 1


        return self.save_excel(workbook, file_name)

    def _group_data(self,data):
        grouped_data = {}
        # Xử lý dữ liệu để nhóm và cộng dồn
        for item in data:
            key = (item['warehouse'], item['ma_hang'], item['color'], item['size'], item['ma_hq'],item['order'])
            if key not in grouped_data:
                # Nếu nhóm chưa tồn tại, tạo mới với các trường số khởi tạo ban đầu
                grouped_data[key] = {
                    'begin_quantity': item['begin_quantity'],
                    'in_purchase': item['in_purchase'],
                    'in_production': item['in_production'],
                    'in_adjust': item['in_adjust'],
                    'in_transfer': item['in_transfer'],
                    'in_other': item['in_other'],
                    'in_total': item['in_total'],
                    'out_production': item['out_production'],
                    'out_supplier': item['out_supplier'],
                    'out_huy': item['out_huy'],
                    'out_adjust': item['out_adjust'],
                    'out_transfer': item['out_transfer'],
                    'out_other': item['out_other'],
                    'out_total': item['out_total'],
                    'end_quantity': item['end_quantity'],
                }
            else:
                # Nếu nhóm đã tồn tại, cập nhật các trường số
                grouped_data[key]['begin_quantity'] += item['begin_quantity']
                grouped_data[key]['in_purchase'] += item['in_purchase']
                grouped_data[key]['in_production'] += item['in_production']
                grouped_data[key]['in_adjust'] += item['in_adjust']
                grouped_data[key]['in_transfer'] += item['in_transfer']
                grouped_data[key]['in_other'] += item['in_other']
                grouped_data[key]['in_total'] += item['in_total']
                grouped_data[key]['out_production'] += item['out_production']
                grouped_data[key]['out_supplier'] += item['out_supplier']
                grouped_data[key]['out_huy'] += item['out_huy']
                grouped_data[key]['out_adjust'] += item['out_adjust']
                grouped_data[key]['out_transfer'] += item['out_transfer']
                grouped_data[key]['out_other'] += item['out_other']
                grouped_data[key]['out_total'] += item['out_total']
                grouped_data[key]['end_quantity'] += item['end_quantity']
           

        # Để xuất kết quả dễ dàng hơn, chuyển dictionary nhóm thành list của dictionaries
        result = []
        for (warehouse, ma_hang, mass_hanbai, bom_add, ma_hq, order), totals in grouped_data.items():
            result.append({
                'warehouse': warehouse,
                'ma_hang': ma_hang,
                'order': order,
                'mass_hanbai': mass_hanbai,
                'bom_add': bom_add,         
                'ma_hq': ma_hq,
                'begin_quantity': totals['begin_quantity'],
                'in_purchase': totals['in_purchase'],
                'in_production': totals['in_production'],
                'in_adjust': totals['in_adjust'],
                'in_transfer': totals['in_transfer'],
                'in_other': totals['in_other'],
                'in_total': totals['in_total'],
                'out_production': totals['out_production'],
                'out_supplier': totals['out_supplier'],
                'out_huy': totals['out_huy'],
                'out_adjust': totals['out_adjust'],
                'out_transfer': totals['out_transfer'],
                'out_other': totals['out_other'],
                'out_total': totals['out_total'],
                'end_quantity': totals['end_quantity'],
            })
        return result
    def _classify_transaction(self, move_line):
        seq = move_line.move_id.picking_type_id.sequence_code or ''
        transaction_type = 'internal'
        warehouse_id = False

        if move_line.location_id.usage == 'supplier' and move_line.location_dest_id.usage == 'internal':
            transaction_type = 'in_purchase'
            warehouse_id = move_line.location_dest_id.warehouse_id.id
        elif move_line.location_id.usage == 'production' and move_line.location_dest_id.usage == 'internal':
            transaction_type = 'in_production'
            warehouse_id = move_line.location_dest_id.warehouse_id.id
        elif move_line.location_id.usage == 'inventory' and move_line.location_dest_id.usage == 'internal':
            transaction_type = 'in_adjust'
            warehouse_id = move_line.location_dest_id.warehouse_id.id
        elif move_line.location_id.usage == 'transit' and move_line.location_dest_id.usage == 'internal':
            transaction_type = 'in_transfer'
            warehouse_id = move_line.location_dest_id.warehouse_id.id
        elif move_line.location_id.usage == 'internal' and move_line.location_dest_id.usage == 'production':
            transaction_type = 'out_production'
            warehouse_id = move_line.location_id.warehouse_id.id
        elif move_line.location_id.usage == 'internal' and move_line.location_dest_id.usage == 'supplier':
            transaction_type = 'out_supplier'
            warehouse_id = move_line.location_id.warehouse_id.id
        elif move_line.location_id.usage == 'internal' and move_line.location_dest_id.usage == 'inventory':
            if move_line.location_dest_id.scrap_location:
                transaction_type = 'out_scrap'
            else:
                transaction_type = 'out_adjust'
            warehouse_id = move_line.location_id.warehouse_id.id
        elif move_line.location_id.usage == 'internal' and move_line.location_dest_id.usage == 'transit':
            transaction_type = 'out_transfer'
            warehouse_id = move_line.location_id.warehouse_id.id
        elif move_line.location_id.usage == 'internal' and move_line.location_dest_id.usage != 'internal':
            transaction_type = 'out_other'
            warehouse_id = move_line.location_id.warehouse_id.id
        elif move_line.location_dest_id.usage == 'internal' and move_line.location_id.usage != 'internal':
            transaction_type = 'in_other'
            warehouse_id = move_line.location_dest_id.warehouse_id.id

        return transaction_type, warehouse_id
        
    def _get_stock_data(self,from_date,to_date):
        transaction_data = {}
        stockMoveLines = self.env['stock.move.line'].search([('date', '<', to_date), ('state', '=', 'done')])
        from_date_datetime = datetime(from_date.year, from_date.month, from_date.day)
        for line in stockMoveLines:
            data_key, warehouse_id = self._classify_transaction(line)
            if warehouse_id:
                product_key = (line.product_id.id, line.lot_id.id if line.lot_id else False,warehouse_id)
                
                if product_key not in transaction_data:
                    transaction_data[product_key] = {'begin_quantity': 0, 'in_purchase': 0,'in_production': 0,
                                                 'in_adjust': 0,'in_transfer': 0, 'in_other': 0,
                                                 'in_total': 0, 'out_production': 0,'out_supplier': 0,
                                                 'out_huy': 0, 'out_adjust': 0,'out_transfer': 0,
                                                 'out_other': 0, 'out_total': 0,'end_quantity': 0,
                                                }
                if data_key != 'internal':
                    if line.date > from_date_datetime:
                        transaction_data[product_key][data_key] += line.quantity
                    else:
                        if 'in_' in data_key:
                            transaction_data[product_key]['begin_quantity'] += line.quantity
                        else:
                            transaction_data[product_key]['begin_quantity'] -= line.quantity
        for key, values in transaction_data.items():
            transaction_data[key]['in_total'] = values['in_purchase'] + values['in_production'] + values['in_adjust'] + values['in_transfer'] + values['in_other']
            transaction_data[key]['out_total'] = values['out_production'] + values['out_supplier'] + values['out_huy'] + values['out_adjust'] + values['out_transfer'] + values['out_other']
            transaction_data[key]['end_quantity'] = transaction_data[key]['begin_quantity'] + transaction_data[key]['in_total'] - transaction_data[key]['out_total']
        return transaction_data

    def _get_values_from_split(self,name, delimiter, expected_parts):
        """Trả về một list các giá trị từ chuỗi bị split, bổ sung giá trị rỗng nếu cần."""
        parts = (name or '').split(delimiter)
        return [parts[i] if i < len(parts) else '' for i in range(expected_parts)]
    
    
    