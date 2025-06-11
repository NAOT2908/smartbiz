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


class HrEmployee(models.Model):
    _name = 'smartbiz.hr.interface'

    def get_barcode_data(self, barcode):
        fields_employee = ['id', 'name', 'barcode', 'work_email', 'image_1920']
        record = self.env['hr.employee'].search_read(
            [('barcode', '=', barcode)], limit=1, fields=fields_employee
        )
        if record:
            return {
                'barcode': barcode,
                'match': True,
                'barcodeType': 'employees',
                'record': record[0],
                'fromCache': False
            }
        return {
            'barcode': barcode,
            'match': False,
            'barcodeType': 'employees',
            'record': False,
            'fromCache': False
        }

    def getData(self, employee_id):
        
        attendance_data = self.env['hr.attendance'].search_read(
            [('employee_id', '=', employee_id)],
            fields=['id', 'employee_id', 'check_in', 'check_out', 'overtime_hours', 'worked_hours'],
            order='check_in desc'
        )

        leave_data = self.env['hr.leave'].search_read(
            [('employee_id', '=', employee_id)],
            fields=['id', 'name', 'employee_id', 'all_employee_ids', 'holiday_status_id', 'state', 'date_from', 'date_to', 'number_of_days', 'activity_ids'],
            order='date_from desc'
        )

        
        overtime_data = self.env['smartbiz_hr.overtime_request'].search_read(
            [('employee_id', '=', employee_id)],
            fields=['id', 'name', 'employee_id', 'start_date', 'end_date', 'duration', 'state'],
            order='start_date desc'
        )
        
        # Truy vấn bảng lương của nhân viên
        payslip_data = self.env['hr.payslip'].search_read(
            [('employee_id', '=', employee_id)],
            fields=['id', 'employee_id', 'date_from', 'date_to', 'number', 'state', 'name', 'net_wage'],
            order='date_from desc'
        )

        # Lấy danh sách ID của các payslip
        payslip_ids = [slip['id'] for slip in payslip_data]

        # Truy vấn file đính kèm liên kết tới các payslip
        attachments = self.env['ir.attachment'].search_read(
            [('res_model', '=', 'hr.payslip'), ('res_id', 'in', payslip_ids)],
            fields=['id', 'name', 'datas', 'res_id', 'res_model', 'mimetype']
        )

        data = {
            'attendance_data': attendance_data,
            'leave_data': leave_data,
            'overtime_data': overtime_data,
            'payslip_data': payslip_data,
        }
        
        return data

    