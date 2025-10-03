# -*- coding: utf-8 -*-

from odoo.tools.float_utils import float_compare, float_is_zero, float_round
from odoo.osv import expression
from odoo import models, fields, api, exceptions,_, tools
from collections import defaultdict
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
            fields=['id', 'employee_id', 'check_in', 'check_out', 'overtime_hours', 'worked_hours', 'state'],
            order='check_in desc'
        )

        leave_data = self.env['hr.leave'].search_read(
            domain_leave,
            fields=['id', 'name', 'employee_id', 'holiday_status_id', 'state', 'date_from', 'date_to', 'number_of_days', 'duration_display'],
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
        # allocation_data = self.env['hr.leave.allocation'].search_read(
        #     [('employee_id', '=', employee_id), ('state', '=', 'validate')],
        #     fields=['id', 'name', 'holiday_status_id', 'duration_display',
        #             'number_of_days_display', 'number_of_days'],
        # )


        data = {
            'hr_data': hr_data,
            'attendance_data': attendance_data,
            'leave_data': leave_data,
            'overtime_data': overtime_data,
            'payslip_data': payslip_data,
            'workentry_data': workentry_data,
        }
        
        return data
    
    def getWorkentrySummary(self, employee_id, date_from=None, date_to=None):
        domain = [('employee_id', '=', employee_id), ('state', '!=', 'conflict')]
        if date_from and date_to:
            domain += ['&', ('date_start', '>=', date_from), ('date_stop', '<=', date_to)]

        work_entries = self.env['hr.work.entry'].search(domain)

        summary_map = defaultdict(lambda: {'total_hours': 0.0, 'total_days': 0.0, 'work_entry_type_name': ''})

        for entry in work_entries:
            if not entry.date_start or not entry.date_stop:
                continue
            hours = (entry.date_stop - entry.date_start).total_seconds() / 3600.0
            days = hours / 8.0 

            type_id = entry.work_entry_type_id.id
            summary_map[type_id]['total_hours'] += hours
            summary_map[type_id]['total_days'] += days
            summary_map[type_id]['work_entry_type_name'] = entry.work_entry_type_id.name

        result = []
        for type_id, vals in summary_map.items():
            result.append({
                'work_entry_type_id': type_id,
                'work_entry_type_name': vals['work_entry_type_name'],
                'total_hours': round(vals['total_hours'], 2),
                'total_days': round(vals['total_days'], 2),
            })

        return result
    
    # def getWorkentrySummary(self, employee_id, date_from=None, date_to=None):
    #     domain = [
    #         ('employee_id', '=', employee_id),
    #         ('state', '!=', 'conflict'),
    #     ]
    #     if date_from and date_to:
    #         domain += ['&', ('date_start', '>=', date_from), ('date_stop', '<=', date_to)]

    #     work_entries = self.env['hr.work.entry'].search(domain)

    #     # lấy tất cả work entry type
    #     work_entry_types = self.env['hr.work.entry.type'].search([])

    #     # init map cho tất cả loại
    #     summary_map = {
    #         wtype.id: {
    #             'total_hours': 0.0,
    #             'total_days': 0.0,
    #             'work_entry_type_name': wtype.name,
    #         }
    #         for wtype in work_entry_types
    #     }

    #     # cộng dồn dữ liệu thật sự
    #     for entry in work_entries:
    #         if not entry.date_start or not entry.date_stop:
    #             continue
    #         hours = (entry.date_stop - entry.date_start).total_seconds() / 3600.0
    #         days = hours / 8.0  # giả định 1 ngày = 8 giờ

    #         type_id = entry.work_entry_type_id.id
    #         if type_id in summary_map:
    #             summary_map[type_id]['total_hours'] += hours
    #             summary_map[type_id]['total_days'] += days

    #     # convert sang list để trả về
    #     result = [
    #         {
    #             'work_entry_type_id': type_id,
    #             'work_entry_type_name': vals['work_entry_type_name'],
    #             'total_hours': round(vals['total_hours'], 2),
    #             'total_days': round(vals['total_days'], 2),
    #         }
    #         for type_id, vals in summary_map.items()
    #     ]

    #     return result

    def getLeaveSummary(self, employee_id):
        results = []
        allocations = self.env['hr.leave.allocation'].search([
            ('employee_id', '=', employee_id),
            ('state', '=', 'validate'),
        ])

        leaves = self.env['hr.leave'].search([
            ('employee_id', '=', employee_id),
            ('state', '=', 'validate'),
        ])

        for lt in allocations.mapped('holiday_status_id'):
            allocs = allocations.filtered(lambda a: a.holiday_status_id == lt)
            used = leaves.filtered(lambda l: l.holiday_status_id == lt)

            if lt.request_unit == "hour":
                allocated_val = sum(allocs.mapped('number_of_hours_display'))
                taken_val = sum(used.mapped('number_of_hours_display'))
                unit_label = "giờ"
            else:  # day
                allocated_val = sum(allocs.mapped('number_of_days'))
                taken_val = sum(used.mapped('number_of_days'))
                unit_label = "ngày"

            remaining_val = allocated_val - taken_val

            results.append({
                'id': lt.id,
                'name': lt.display_name,
                'request_unit': lt.request_unit,
                'allocated': allocated_val,
                'taken': taken_val,
                'remaining': remaining_val,
                'allocated_display': f"{allocated_val} {unit_label}",
                'taken_display': f"{taken_val} {unit_label}",
                'remaining_display': f"{remaining_val} {unit_label}",
            })

        return results

    
    def getAttendanceAlert(self, employee_id, date_from=None, date_to=None):
        domain = [
            ('employee_id', '=', employee_id)
        ]
        if date_from and date_to:
            domain += ['&', ('block_start', '>=', date_from), ('block_end', '<=', date_to)]
        alert_data = self.env['smartbiz_hr.attendance_alert'].search_read(
            domain,
            fields=[
                'id', 'name', 'employee_id',
                'alert_type', 'note', 'date', 'block_start', 'block_end', 'state'
            ],
            order='date desc',
        )
        return alert_data
    
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
                'take_with': leave_data.get('take_with', ''),
                'plate_number': leave_data.get('plate_number', ''),
            }

            base_date = leave_data.get('date_from')[:10]

            # --- Nghỉ theo giờ ---
            hour_from = leave_data.get('request_hour_from')
            hour_to = leave_data.get('request_hour_to')
            if hour_from and hour_to:
                leave_vals['request_unit_hours'] = True

                hour_from = float(hour_from)
                hour_to = float(hour_to)

                start_hour = int(hour_from)
                start_minute = int(round((hour_from - start_hour) * 60))
                end_hour = int(hour_to)
                end_minute = int(round((hour_to - end_hour) * 60))

                date_from = datetime.strptime(base_date, "%Y-%m-%d") + timedelta(hours=start_hour, minutes=start_minute)
                date_to = datetime.strptime(base_date, "%Y-%m-%d") + timedelta(hours=end_hour, minutes=end_minute)

                leave_vals.update({
                    'request_date_from': date_from.strftime("%Y-%m-%d %H:%M:%S"),
                    'request_date_to': date_to.strftime("%Y-%m-%d %H:%M:%S"),
                    'request_hour_from': str(leave_data.get('request_hour_from')),
                    'request_hour_to': str(leave_data.get('request_hour_to')),
                })
            else:
                # --- Nghỉ nguyên ngày ---
                leave_vals['request_date_from'] = base_date
                leave_vals['request_date_to'] = (leave_data.get('date_to')[:10] 
                                                if leave_data.get('date_to') else base_date)

            leave = self.env['hr.leave'].create(leave_vals)
            results.append(self.getData(employee_id))
        return results

    def create_overtime(self, employee_ids, overtime_data, employee_id):
        """
        Tạo 1 overtime request với nhiều request_line cho danh sách employee_ids,
        sau đó submit luôn và trả về getData().
        """
        # Tạo overtime request cha
        overtime = self.env['smartbiz_hr.overtime_request'].create({
            'name': overtime_data.get('name', ''),
            'start_date': overtime_data.get('start_date'),
            'end_date': overtime_data.get('end_date'),
            'note': overtime_data.get('note', ''),
            'employee_ids': [(6, 0, employee_ids)],
        })

        # Chuẩn bị lines cho từng nhân viên
        line_vals = []
        for emp_id in employee_ids:
            line_vals.append({
                'request_id': overtime.id,
                'employee_id': emp_id,
                'start_date': overtime_data.get('start_date'),
                'end_date': overtime_data.get('end_date'),
                'state': 'draft',
            })
        self.env['smartbiz_hr.request_line'].create(line_vals)

        # Submit luôn
        overtime.action_draft_submit()

        # Trả về data (theo employee_id của request gọi lên)
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

    def create_alert_attendance(self, employee_id, alert_data):
 
        self.env['smartbiz_hr.attendance_alert'].browse(alert_data.get('id')).write({'state': 'ack'})
        
        results = []
      
        self.env['hr.attendance'].create({
                'employee_id': employee_id,
                'check_in': alert_data.get('block_start'),
                'check_out': alert_data.get('block_end'),
                'state': 'to_submit',
            })
        results.append(self.getData(employee_id))
        return results
    
    
class ResUsers(models.Model):
    _inherit = "res.users"

class HrLeave(models.Model):
    _inherit = "hr.leave"

    plate_number = fields.Char(string="Plate Number")
    take_with = fields.Char(string="Take With")
    
    

