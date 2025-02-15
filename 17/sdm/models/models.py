# -*- coding: utf-8 -*-

from odoo.osv import expression
from odoo import models, fields, api, exceptions,_, tools
import os
import base64,pytz,logging
from datetime import datetime, timedelta
import datetime as date_time
import random
from odoo.exceptions import UserError, ValidationError
from odoo.tools import config, float_compare
_logger = logging.getLogger(__name__)
from io import BytesIO
import xlsxwriter
from openpyxl import load_workbook

class sdm_Location(models.Model):
    _name = "sdm.location"
    _description = "Location"
    name = fields.Char(string='Name')
    parent_location_id = fields.Many2one('sdm.location', string='Parent Location')
    children_location_ids = fields.One2many('sdm.location', 'parent_location_id')


class sdm_DeviceType(models.Model):
    _name = "sdm.device_type"
    _description = "Device Type"
    name = fields.Char(string='Name')
    device_ids = fields.One2many('sdm.device', 'device_type_id')
    notification_ids = fields.One2many('sdm.notification', 'device_type_id')


class sdm_Device(models.Model):
    _name = "sdm.device"
    _description = "Device"
    name = fields.Char(string='Name')
    code = fields.Char(string='Code')
    device_type_id = fields.Many2one('sdm.device_type', string='Device Type')
    location_id = fields.Many2one('sdm.location', string='Location')
    status = fields.Selection([('not_available','Not Available'),('normal','Normal'),('abnormal','Abnormal'),], string='Status', default = 'not_available')
    last_checked = fields.Datetime(string='Last Checked')
    iot_id = fields.Char(string='IoT ID')


    def write(self, vals):
        for record in self:
            old_status = record.status
            res = super(sdm_Device, record).write(vals)
            new_status = record.status
            if 'status' in vals:
                # Trạng thái đã thay đổi
                record._check_status_change(old_status, new_status)
        return res

    def _check_status_change(self, old_status, new_status):
        _logger.info('Device %s status changed from %s to %s', self.name, old_status, new_status)
        notification_obj = self.env['sdm.notification']

        notification_type_code = False

        if old_status == 'not_available' and new_status != 'not_available':
            notification_type_code = 'device_operational'
        elif old_status != 'not_available' and new_status == 'not_available':
            notification_type_code = 'device_not_operating'
        elif old_status == 'normal' and new_status == 'abnormal':
            notification_type_code = 'underheating'
        elif old_status == 'abnormal' and new_status == 'normal':
            notification_type_code = 'back_to_normal'

        if notification_type_code:
            # Lấy hoặc tạo notification_type tương ứng
            notification_type = self.env['sdm.notification_type'].search([
                ('code', '=', notification_type_code)
            ], limit=1)
            if not notification_type:
                notification_type = self.env['sdm.notification_type'].create({
                    'name': notification_type_code.replace('_', ' ').title(),
                    'code': notification_type_code,
                })
                _logger.info('Created new Notification Type with code %s', notification_type_code)

            # Lấy các thiết bị cùng trạng thái
            if notification_type_code == 'device_operational' or notification_type_code == 'back_to_normal':
                devices = self
            elif notification_type_code == 'device_not_operating' or notification_type_code == 'underheating':
                devices = self.search([('status', '=', new_status)])           

            # Lấy các cấu hình thông báo
            notifications = notification_obj.search([
                ('device_type_id', '=', self.device_type_id.id),
                ('notification_type_id', '=', notification_type.id)
            ])
            if not notifications:
                default_notification = notification_obj.create({
                    'name': notification_type.name,
                    'device_type_id': self.device_type_id.id,
                    'notification_type_id': notification_type.id,
                    'time_in_day': 8,
                    'interval_hours': 1,
                    'max_notice': 5,
                    'partner_ids': [(6, 0, self.env.ref('base.partner_admin').ids)],  # Gửi đến admin
                })
                notifications = default_notification

            # Gửi thông báo chung cho tất cả thiết bị
            for notification in notifications:
                self._send_aggregated_notification(notification, devices)


    def _send_aggregated_notification(self, notification, devices):
        # Chuẩn bị danh sách trạng thái
        status_mapping = dict(self.fields_get(allfields=['status'])['status']['selection'])

        # Tạo danh sách thiết bị
        device_list = [
            {
                'name': device.name,
                'code': device.code,
                'status': status_mapping.get(device.status, 'N/A'),
                'last_checked': device.last_checked.strftime('%Y-%m-%d %H:%M:%S') if device.last_checked else 'N/A',
            }
            for device in devices
        ]

        # Chuẩn bị nội dung email dựa trên loại thông báo
        if notification.notification_type_id.code == 'all_devices_operational':
            subject = 'Tất cả thiết bị đều hoạt động bình thường'
            body_html = """
                <p>Kính gửi Quý khách,</p>
                <p>Tất cả các thiết bị hiện đang hoạt động bình thường.</p>
                <p>Trân trọng,<br>Công ty của bạn</p>
            """
        elif notification.notification_type_id.code == 'devices_not_available':
            # Tạo bảng HTML danh sách thiết bị
            device_list_html = """
            <table border="1" cellpadding="5" cellspacing="0">
                <tr>
                    <th>Tên thiết bị</th>
                    <th>Mã thiết bị</th>
                    <th>Trạng thái</th>
                    <th>Kiểm tra lần cuối</th>
                </tr>
            """
            for device in device_list:
                device_list_html += f"""
                <tr>
                    <td>{device['name']}</td>
                    <td>{device['code']}</td>
                    <td>{device['status']}</td>
                    <td>{device['last_checked']}</td>
                </tr>
                """
            device_list_html += "</table>"

            subject = 'Danh sách thiết bị không hoạt động'
            body_html = f"""
                <p>Kính gửi Quý khách,</p>
                <p>Các thiết bị sau hiện đang không hoạt động:</p>
                {device_list_html}
                <p>Vui lòng kiểm tra các thiết bị.</p>
                <p>Trân trọng,<br>Công ty của bạn</p>
            """
        elif notification.notification_type_id.code == 'underheating':
            # Tạo bảng HTML danh sách thiết bị
            device_list_html = """
            <table border="1" cellpadding="5" cellspacing="0">
                <tr>
                    <th>Tên thiết bị</th>
                    <th>Mã thiết bị</th>
                    <th>Trạng thái</th>
                    <th>Kiểm tra lần cuối</th>
                </tr>
            """
            for device in device_list:
                device_list_html += f"""
                <tr>
                    <td>{device['name']}</td>
                    <td>{device['code']}</td>
                    <td>{device['status']}</td>
                    <td>{device['last_checked']}</td>
                </tr>
                """
            device_list_html += "</table>"

            subject = 'Danh sách thiết bị bất thường'
            body_html = f"""
                <p>Kính gửi Quý khách,</p>
                <p>Các thiết bị sau hiện đang ở trạng thái bất thường:</p>
                {device_list_html}
                <p>Vui lòng kiểm tra và xử lý.</p>
                <p>Trân trọng,<br>Công ty của bạn</p>
            """


        

        # Danh sách người nhận
        # recipient_emails = ",".join(notification.partner_ids.mapped('email'))
        # email_from = 'AIS Notification'
        primary_recipient = notification.partner_ids[0].email if notification.partner_ids else None
        cc_recipients = notification.partner_ids[1:].mapped('email')
       
        # Kiểm tra và gửi email
        if primary_recipient:
            if notification.notification_template_id:
                # Sử dụng template email
                template = notification.notification_template_id
                body_html = template._render_template(
                    template.body_html, 'sdm.device', self.ids,engine='qweb',
                    add_context={'devices': device_list}
                )[self.id]
                subject = template._render_template(
                    template.subject, 'sdm.device', self.ids,engine='qweb',
                    add_context={'devices': device_list},
                )[self.id]
                email_from = template.email_from

            # Tạo email
            mail_values = {
                'email_from':email_from,
                'subject': subject,
                'body_html': body_html,
                'email_to': primary_recipient,
                'email_cc': ','.join(cc_recipients),
            }
            mail = self.env['mail.mail'].create(mail_values)
            

        # Ghi log thông báo
        self.env['sdm.notification_log'].create({
            'notification_id': notification.id,
            'notification_type_id': notification.notification_type_id.id,
            'time': fields.Datetime.now(),
            'subject': subject,
            'body': body_html,
            
        })


    @api.model
    def send_repeat_notifications(self):
        # Lấy múi giờ của người dùng hoặc múi giờ mặc định
        user_tz = self.env.user.tz or 'UTC'
        local_tz = pytz.timezone(user_tz)

        # Lấy thời gian hiện tại theo múi giờ địa phương
        current_time_local = datetime.now(local_tz)
        current_time_in_hours = current_time_local.hour + current_time_local.minute / 60.0

        # Danh sách các mã notification_type cần xử lý
        notification_type_codes = ['all_devices_operational', 'devices_not_available', 'underheating']

        for notification_type_code in notification_type_codes:
            # Lấy hoặc tạo notification_type tương ứng
            notification_type = self.env['sdm.notification_type'].search([
                ('code', '=', notification_type_code)
            ], limit=1)
            if not notification_type:
                notification_type = self.env['sdm.notification_type'].create({
                    'name': 'Tất cả thiết bị hoạt động bình thường' if notification_type_code == 'all_devices_operational' else
                            'Thiết bị không hoạt động' if notification_type_code == 'devices_not_available' else
                            'Thiết bị bất thường',
                    'code': notification_type_code,
                })

            # Lấy hoặc tạo notification tương ứng
            notification = self.env['sdm.notification'].search([
                ('notification_type_id', '=', notification_type.id)
            ], limit=1)
            if not notification:
                notification = self.env['sdm.notification'].create({
                    'name': notification_type.name,
                    'notification_type_id': notification_type.id,
                    'time_in_day': 8.0,  # Bạn có thể thay đổi giá trị này theo nhu cầu
                    'interval_hours': 1.0,  # Đối với 'underheating'
                    'max_notice': 5,        # Đối với 'underheating'
                    'partner_ids': [(6, 0, self.env.ref('base.partner_admin').ids)],
                })

            # Kiểm tra nếu đã gửi thông báo trong ngày hôm nay chưa (đối với thông báo hàng ngày)
            last_log_today = self.env['sdm.notification_log'].search([
                ('notification_id', '=', notification.id),
                ('time', '>=', datetime.combine(current_time_local.date(), datetime.min.time()).astimezone(pytz.UTC)),
                ('time', '<=', datetime.combine(current_time_local.date(), datetime.max.time()).astimezone(pytz.UTC)),
            ], limit=1)

            # Tính toán thời gian chênh lệch giữa thời điểm hiện tại và time_in_day
            time_difference = abs(current_time_in_hours - notification.time_in_day)
            # Do cron chạy mỗi 5 phút, chúng ta cho phép khoảng chênh lệch nhỏ (5 phút ~ 0.084 giờ)

            if notification_type_code in ['all_devices_operational', 'devices_not_available']:
                if last_log_today:
                    continue  # Đã gửi thông báo hôm nay rồi

                if time_difference <= 0.084:
                    # Thực hiện kiểm tra trạng thái thiết bị
                    devices = self.search([])
                    devices_not_available = devices.filtered(lambda d: d.status == 'not_available')

                    if notification_type_code == 'all_devices_operational' and not devices_not_available:
                        # Tất cả thiết bị hoạt động bình thường
                        devices_to_notify = devices
                        self._send_aggregated_notification(notification, devices_to_notify)
                    elif notification_type_code == 'devices_not_available' and devices_not_available:
                        # Có thiết bị không hoạt động
                        devices_to_notify = devices_not_available
                        self._send_aggregated_notification(notification, devices_to_notify)

            elif notification_type_code == 'underheating':
                # Xử lý thông báo cho thiết bị 'abnormal'
                devices_abnormal = self.search([('status', '=', 'abnormal')])
                if devices_abnormal:
                    # Kiểm tra số lần đã gửi thông báo trong khoảng thời gian xác định
                    time_threshold = fields.Datetime.now() - timedelta(hours=notification.interval_hours)
                    logs = self.env['sdm.notification_log'].search([
                        ('notification_id', '=', notification.id),
                        ('time', '>=', time_threshold)
                    ])
                    if len(logs) < notification.max_notice:
                        devices_to_notify = devices_abnormal
                        self._send_aggregated_notification(notification, devices_to_notify)
                    else:
                        _logger.info("Max notifications reached for notification: %s", notification.name)

class sdm_NotificationType(models.Model):
    _name = "sdm.notification_type"
    _description = "Notification Type"
    name = fields.Char(string='Name')
    code = fields.Char(string='Code')
    notification_ids = fields.One2many('sdm.notification', 'notification_type_id')


class sdm_Notification(models.Model):
    _name = "sdm.notification"
    _description = "Notification"
    name = fields.Char(string='Name')
    device_type_id = fields.Many2one('sdm.device_type', string='Device Type')
    notification_type_id = fields.Many2one('sdm.notification_type', string='Notification Type')
    time_in_day = fields.Float(string='Time in day')
    interval_hours = fields.Float(string='Interval Hours')
    max_notice = fields.Integer(string='Max Notice')
    notification_template_id = fields.Many2one('mail.template', string='Notification Template')
    partner_ids = fields.Many2many('res.partner', string='Partner')
    model_id = fields.Many2one('ir.model', string='Model', compute='_compute_model_id', store=True)


    @api.depends('name')
    def _compute_model_id(self):
        for record in self:
            record.model_id = self.env['ir.model'].search([['model','=','sdm.device']],limit=1).id

class sdm_NotificationLog(models.Model):
    _name = "sdm.notification_log"
    _rec_name = "notification_id"
    _description = "Notification Log"
    notification_id = fields.Many2one('sdm.notification', string='Notification')
    device_id = fields.Many2one('sdm.device', string='Device')
    notification_type_id = fields.Many2one('sdm.notification_type', string='Notification Type')
    time = fields.Datetime(string='Time')
    subject = fields.Char(string='Subject')
    body = fields.Html(string='Body')


