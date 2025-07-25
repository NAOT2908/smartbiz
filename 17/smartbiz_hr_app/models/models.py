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
        fields_employee = ['id', 'name', 'barcode', 'work_email', 'image_1920', 'pin']
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
        
        hr_data = self.env['hr.employee'].search_read(
            [('id', '=', employee_id)],
            fields=['id', 'name', 'barcode', 'work_email', 'image_1920', 'pin'],
            
        )
        
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
        allocation_data = self.env['hr.leave.allocation'].search_read(
            [
                ('employee_id', '=', employee_id),
                ('state', '=', 'validate')
            ],
            fields=['id', 'name', 'holiday_status_id', 'duration_display', 'number_of_days_display', 'number_of_days'],
        )
        # overtime_data = self.env['smartbiz_hr.overtime_request'].search_read(
        #     [('employee_ids', 'in', employee_id)],
        #     fields=['id', 'name', 'employee_ids', 'start_date', 'end_date', 'duration', 'state'],
        #     order='start_date desc'
        # )
        overtime_data = self.env['smartbiz_hr.request_line'].search_read(
            [('employee_id', '=', employee_id)],
            fields=['id', 'employee_id', 'start_date', 'end_date', 'duration', 'state', 'request_id'],
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
            'hr_data': hr_data,
            'attendance_data': attendance_data,
            'leave_data': leave_data,
            'overtime_data': overtime_data,
            'payslip_data': payslip_data,
            'allocations': allocation_data,
        }
        
        return data

    def create_leave(self, employee_ids, leave_data):
        """
        Tạo yêu cầu nghỉ phép cho nhiều nhân viên.
        :param employee_ids: Danh sách ID của nhân viên
        :param leave_data: Dữ liệu nghỉ phép chung
        :return: Danh sách kết quả getData
        """
        results = []
        for employee_id in employee_ids:
            self.env['hr.leave'].create({
                'employee_id': employee_id,
                'holiday_status_id': leave_data.get('holiday_status_id'),
                'date_from': leave_data.get('date_from'),
                'date_to': leave_data.get('date_to'),
                'number_of_days': leave_data.get('number_of_days'),
                'name': leave_data.get('name', ''),
            })
            results.append(self.getData(employee_id))
        return results

    def create_overtime(self, employee_ids, overtime_data, employee_id):
        """
        Tạo yêu cầu làm thêm giờ riêng cho từng nhân viên,
        submit luôn và trả về getData.
        """
        results = []
        for employee_id in employee_ids:
            overtime = self.env['smartbiz_hr.overtime_request'].create({
                'employee_ids': [(6, 0, [employee_id])],
                'start_date': overtime_data.get('start_date'),
                'end_date': overtime_data.get('end_date'),
                'name': overtime_data.get('name', ''),
            })
            overtime.action_draft_submit()
            
        results = self.getData(employee_id)
        return results



    def create_attendance(self, employee_ids, attendance_data):
        """
        Tạo bản ghi chấm công cho nhiều nhân viên.
        :param employee_ids: Danh sách ID của nhân viên
        :param attendance_data: Dữ liệu chấm công chung
        :return: Danh sách kết quả getData
        """
        results = []
        for employee_id in employee_ids:
            self.env['hr.attendance'].create({
                'employee_id': employee_id,
                'check_in': attendance_data.get('check_in'),
                'check_out': attendance_data.get('check_out'),
                'worked_hours': attendance_data.get('worked_hours', 0.0),
                'overtime_hours': attendance_data.get('overtime_hours', 0.0),
            })
            results.append(self.getData(employee_id))
        return results
