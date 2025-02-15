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


class mrp_Workcenter(models.Model):
    _inherit = ['mrp.workcenter']
    
    def get_barcode_data(self, barcode, filters, barcodeType):
    # Các trường cần lấy cho từng loại barcodeType
        fields_workcenter = ['id', 'name', 'code', 'production_line_id']  # Thêm các trường cơ bản mà bạn muốn
        filters_employee =  ['id', 'name', 'barcode']
        if barcodeType:
            if barcodeType == 'workcenters':
                # Lấy thông tin Workcenter và thêm các trường cần thiết
                record = self.env['mrp.workcenter'].search_read([('code', '=', barcode)], limit=1, fields=fields_workcenter)
            elif barcodeType == 'employees':
                # Lấy thông tin Employee và thêm các trường cần thiết
                record = self.env['hr.employee'].search_read([('barcode', '=', barcode)], limit=1, fields=filters_employee)
            
            if record:
                return {'barcode': barcode, 'match': True, 'barcodeType': barcodeType, 'record': record[0], 'fromCache': False}
        
        else:
            # Nếu không có barcodeType, tìm theo 'workcenters' hoặc 'employees' mặc định
            record = self.env['mrp.workcenter'].search_read([('code', '=', barcode)], limit=1, fields=fields_workcenter)
            if record:
                return {'barcode': barcode, 'match': True, 'barcodeType': 'workcenters', 'record': record[0], 'fromCache': False}
            
            record = self.env['hr.employee'].search_read([('barcode', '=', barcode)], limit=1, fields=filters_employee)
            if record:
                return {'barcode': barcode, 'match': True, 'barcodeType': 'employees', 'record': record[0], 'fromCache': False}

        # Nếu không tìm thấy kết quả nào
        return {'barcode': barcode, 'match': False, 'barcodeType': barcodeType, 'record': False, 'fromCache': False}
