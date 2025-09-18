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

    def getData(self, employee_id, date_from=None, date_to=None):
        """Lấy dữ liệu nhân viên theo khoảng ngày"""

        domain_attendance = [('employee_id', '=', employee_id)]
        domain_leave = [('employee_id', '=', employee_id)]
        domain_work = [('employee_id', '=', employee_id), ('state', '!=', 'conflict')]
        domain_payslip = [('employee_id', '=', employee_id)]
        domain_overtime = [('employee_id', '=', employee_id)]
        
        if date_from and date_to:
            domain_attendance += ['&', ('check_in', '>=', date_from), ('check_out', '<=', date_to)]
            domain_leave += ['&', ('date_from', '>=', date_from), ('date_to', '<=', date_to)]
            domain_work += ['&', ('date_start', '>=', date_from), ('date_stop', '<=', date_to)]
            domain_payslip += ['&', ('date_from', '>=', date_from), ('date_to', '<=', date_to)]
            domain_overtime += ['&', ('start_date', '>=', date_from), ('end_date', '<=', date_to)]
           
    
        # raise exceptions.UserError(_(
        #         "Chỉ được chọn một trong hai khoảng thời gian: từ ngày đến ngày hoặc khoảng thời gian.\n"
        #         "DEBUG: domain_work=%s, domain_attendance=%s" % (domain_work, domain_attendance)
        #     ))
        attendance_data = self.env['hr.attendance'].search_read(
            domain_attendance,
            fields=['id', 'employee_id', 'check_in', 'check_out', 'overtime_hours', 'worked_hours'],
            order='check_in desc'
        )

        leave_data = self.env['hr.leave'].search_read(
            domain_leave,
            fields=['id', 'name', 'employee_id', 'holiday_status_id', 'state', 'date_from', 'date_to', 'number_of_days'],
            order='date_from desc'
        )

        workentry_data = self.env['hr.work.entry'].search_read(
            domain_work,
            fields=['id', 'name', 'employee_id', 'date_start', 'date_stop', 'duration', 'state', 'work_entry_type_id', 'code', 'leave_id'],
            order='date_start desc'
        )
        

        overtime_data = self.env['smartbiz_hr.request_line'].search_read(
            domain_overtime,
            fields=['id', 'request_id', 'employee_id', 'start_date', 'end_date', 'duration', 'state', 'request_id'],
            order='start_date desc'
        )

        payslip_data = self.env['hr.payslip'].search_read(
            domain_payslip,
            fields=['id', 'employee_id', 'date_from', 'date_to', 'net_wage'],
            order='date_from desc'
        )


        # hr_data (chỉ lấy 1 lần, không cần lọc theo ngày)
        hr_data = self.env['hr.employee'].search_read(
            [('id', '=', employee_id)],
            fields=['id', 'name', 'barcode', 'work_email', 'image_1920', 'pin'],
        )


        # leave allocation (không cần lọc theo ngày vì allocation thường dài hạn)
        allocation_data = self.env['hr.leave.allocation'].search_read(
            [('employee_id', '=', employee_id), ('state', '=', 'validate')],
            fields=['id', 'name', 'holiday_status_id', 'duration_display',
                    'number_of_days_display', 'number_of_days'],
        )


        data = {
            'hr_data': hr_data,
            'attendance_data': attendance_data,
            'leave_data': leave_data,
            'overtime_data': overtime_data,
            'payslip_data': payslip_data,
            'allocations': allocation_data,
            'workentry_data': workentry_data,
        }
        
        return data

    def create_leave(self, employee_ids, leave_data):
        """
        Tạo yêu cầu nghỉ phép cho nhiều nhân viên.
        """
        results = []
        for employee_id in employee_ids:
            leave_vals = {
                'employee_id': employee_id,
                'holiday_status_id': leave_data.get('holiday_status_id'),
                'name': leave_data.get('note', ''),  # lý do
            }

            # Nếu nghỉ nửa ngày
            if leave_data.get('request_unit_half') == "half_day":
                leave_vals['request_unit_half'] = True
                leave_vals['request_date_from'] = leave_data.get('date_from')[:10]
                leave_vals['request_date_to'] = leave_data.get('date_from')[:10]

            # Nếu nghỉ theo giờ
            elif leave_data.get('request_unit_hours'):
                leave_vals['request_unit_hours'] = True

                # Ngày gốc
                base_date = leave_data.get('date_from')[:10]

                # Lấy giờ float
                hour_from = float(leave_data.get('request_hour_from'))
                hour_to = float(leave_data.get('request_hour_to'))

                # Tách giờ và phút
                start_hour = int(hour_from)
                start_minute = int((hour_from - start_hour) * 60)

                end_hour = int(hour_to)
                end_minute = int((hour_to - end_hour) * 60)

                # Ghép datetime
                date_from = datetime.strptime(base_date, "%Y-%m-%d") + timedelta(hours=start_hour, minutes=start_minute)
                date_to = datetime.strptime(base_date, "%Y-%m-%d") + timedelta(hours=end_hour, minutes=end_minute)

                leave_vals['date_from'] = date_from.strftime("%Y-%m-%d %H:%M:%S")
                leave_vals['date_to'] = date_to.strftime("%Y-%m-%d %H:%M:%S")

            # Nếu nghỉ nguyên ngày
            else:
                leave_vals['request_date_from'] = leave_data.get('date_from')[:10]
                leave_vals['request_date_to'] = (
                    leave_data.get('date_to')[:10] if leave_data.get('date_to') else leave_data.get('date_from')[:10]
                )

            leave = self.env['hr.leave'].create(leave_vals)
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

class ResUsers(models.Model):
    _inherit = "res.users"




