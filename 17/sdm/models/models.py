# -*- coding: utf-8 -*-

import logging
import math
from datetime import datetime, timedelta

import pytz
from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


# =========================
#  Location & Device Type
# =========================
class sdm_Location(models.Model):
    _name = "sdm.location"
    _description = "Location"

    name = fields.Char(string="Name")
    parent_location_id = fields.Many2one("sdm.location", string="Parent Location")
    children_location_ids = fields.One2many("sdm.location", "parent_location_id")


class sdm_DeviceType(models.Model):
    _name = "sdm.device_type"
    _description = "Device Type"

    name = fields.Char(string="Name")
    device_ids = fields.One2many("sdm.device", "device_type_id")
    notification_ids = fields.One2many("sdm.notification", "device_type_id")


# =========================
#  Device (Core)
# =========================
class sdm_Device(models.Model):
    _name = "sdm.device"
    _description = "Device"

    # Thông tin cơ bản
    name = fields.Char(string="Name")
    code = fields.Char(string="Code", index=True)
    device_type_id = fields.Many2one("sdm.device_type", string="Device Type", index=True)
    location_id = fields.Many2one("sdm.location", string="Location", index=True)

    status = fields.Selection(
        [
            ("not_available", "Not Available"),
            ("normal", "Normal"),
            ("abnormal", "Abnormal"),
            ("maintaince", "Maintaince"),
        ],
        string="Status",
        default="normal",
        index=True,
    )

    last_checked = fields.Datetime(string="Last Checked", index=True)      # lúc bản ghi được ghi gần nhất
    last_signal_at = fields.Datetime(string="Last Signal At", index=True)  # lúc nhận tín hiệu (therm/io) mới nhất

    iot_id = fields.Char(string="IoT ID", index=True)
    temperature = fields.Float(string="Temperature", digits=(16, 2))
    io_alarm = fields.Boolean(string="IO Alarm (Furnace Off)")  # True = lò dừng đốt

    # Ánh xạ tín hiệu
    iot_therm_unitid = fields.Integer(string="Therm UnitID", index=True)
    iot_io_unitid = fields.Integer(string="IO UnitID", index=True)
    iot_io_channel = fields.Integer(string="IO Channel", default=0, index=True)
    iot_temp_scale = fields.Float(string="Temp Scale (raw→°C)", default=0.1)

    # Ngưỡng & timeout (ngưỡng riêng theo thiết bị)
    temp_threshold = fields.Float(string="Temp Threshold (°C)", default=620.0, help="Ngưỡng nhiệt dưới mức này coi là bất thường.")
    offline_timeout_sec = fields.Integer(string="Offline Timeout (s)", default=180)

    # Cờ hỗ trợ lọc nhanh theo ngưỡng riêng
    is_below_threshold = fields.Boolean(string="Below Threshold", compute="_compute_threshold_flags", store=True, index=True)

    # ========= Compute flags theo ngưỡng riêng =========
    @api.depends('temperature', 'temp_threshold')
    def _compute_threshold_flags(self):
        for r in self:
            thr = r.temp_threshold or 620.0
            r.is_below_threshold = (r.temperature is not None and r.temperature < thr)

    # ========= Inference (pure) =========
    def _status_from_signals(self, *, temp=None, io_alarm=None, offline=False):
        """Suy trạng thái theo luật:
           - maintaince: giữ nguyên
           - offline → not_available
           - io_alarm True → abnormal
           - temp < threshold → abnormal
           - còn lại → normal
        """
        self.ensure_one()
        if self.status == "maintaince":
            return "maintaince"
        if offline:
            return "not_available"
        if io_alarm is True:
            return "abnormal"
        thr = self.temp_threshold or 620.0
        if temp is not None and temp < thr:
            return "abnormal"
        return "normal"

    # ========= Temperature transition (dùng threshold riêng) =========
    def _check_temperature_transition(self, old_temp, new_temp):
        self.ensure_one()
        _logger.info("Device %s thay đổi nhiệt độ từ %s lên %s", self.name, old_temp, new_temp)
        if self.status == "maintaince" or old_temp is None:
            return None
        thr = self.temp_threshold or 620.0
        if old_temp >= thr and new_temp < thr:
            return "temperature_low"
        elif old_temp < thr and new_temp >= thr:
            return "temperature_back_to_normal"
        return None

    # ========= Write tối ưu: tự gộp status khi chỉ đổi temperature =========
    def write(self, vals):
        before = {r.id: (r.status, r.temperature) for r in self}
        single = len(self) == 1

        # Nếu chỉ đổi temperature mà chưa có status → tự suy và gộp vào vals (ghi 1 lần)
        if single and "temperature" in vals and "status" not in vals:
            r = self
            predicted = r._status_from_signals(temp=vals["temperature"])
            if predicted and predicted != r.status and r.status != "maintaince":
                vals = dict(vals, status=predicted)

        res = super().write(vals)

        # Sau ghi: bắn thông báo dựa thay đổi thực tế
        for r in self:
            old_status, old_temp = before[r.id]
            new_status, new_temp = r.status, r.temperature

            if "status" in vals and new_status != old_status:
                r._check_status_change(old_status, new_status)

            if "temperature" in vals:
                code = r._check_temperature_transition(old_temp, new_temp)
                if code in ("temperature_low", "temperature_back_to_normal"):
                    r._send_temperature_notification(code)

        return res

    # ========= API cho Node-RED: ingest snapshot thô =========
    @api.model
    def ingest_iot_snapshot(self, payload=None, *args, **kwargs):
        """Nhận snapshot:
        {
          "therm": { "1": {"raw":6620,"value":662.0,"lastUpdate": 1757383409884, ...}, ... },
          "io":    { "21:0": {"value":0,"lastUpdate": 1757383409571, ...}, ... }
        }
        - Chấp nhận: args=[payload_dict] hoặc [[payload_dict]]; kwargs={'payload': dict}
        """
        data = payload

        # Chuẩn hóa input (tránh 'list' object has no attribute 'get')
        if data is None and kwargs:
            data = kwargs.get("payload") or kwargs
        while isinstance(data, list) and data:
            data = data[0]
        if not isinstance(data, dict):
            raise UserError(_("Payload không hợp lệ. Cần dict, nhận: %s") % type(data).__name__)

        therm = (data.get("therm") or {}) if isinstance(data.get("therm"), dict) else {}
        io = (data.get("io") or {}) if isinstance(data.get("io"), dict) else {}

        # index nhanh
        therm_by_unit = {}
        for k, v in therm.items():
            try:
                uid = int(k)
                therm_by_unit[uid] = v
            except Exception:
                continue

        io_by_key = {}
        for k, v in io.items():
            io_by_key[str(k)] = v

        # chỉ các thiết bị có ít nhất 1 mapping
        devices = self.search(["|", ("iot_therm_unitid", "!=", False), ("iot_io_unitid", "!=", False)])

        updated = 0
        offline_count = 0
        TEMP_EPS = 0.5
        now_dt = fields.Datetime.now()

        def _ts_ms(x):
            try:
                return int(x)
            except Exception:
                return 0

        for d in devices:
            # Lưu trước để notify chính xác
            old_status = d.status
            old_temp = d.temperature

            # Therm
            new_temp = d.temperature
            therm_s = therm_by_unit.get(d.iot_therm_unitid) if d.iot_therm_unitid else None
            if therm_s:
                if isinstance(therm_s.get("value"), (int, float)):
                    new_temp = round(float(therm_s["value"]), 1)
                elif isinstance(therm_s.get("raw"), (int, float)):
                    scale = d.iot_temp_scale or 0.1
                    new_temp = round(float(therm_s["raw"]) * scale, 1)

            # IO
            io_alarm = d.io_alarm
            io_s = None
            if d.iot_io_unitid is not False and d.iot_io_unitid is not None:
                key = f"{d.iot_io_unitid}:{d.iot_io_channel or 0}"
                io_s = io_by_key.get(key)
                if io_s and "value" in io_s:
                    io_alarm = bool(io_s["value"])

            # lastUpdate → offline?
            last_ms = 0
            if therm_s and therm_s.get("lastUpdate"):
                last_ms = max(last_ms, _ts_ms(therm_s["lastUpdate"]))
            if io_s and io_s.get("lastUpdate"):
                last_ms = max(last_ms, _ts_ms(io_s["lastUpdate"]))

            last_signal_at = None
            if last_ms > 0:
                last_signal_at = datetime.utcfromtimestamp(last_ms / 1000.0)

            offline = False
            if last_signal_at:
                offline = (now_dt - last_signal_at) > timedelta(seconds=(d.offline_timeout_sec or 180))

            if offline:
                offline_count += 1

            # Suy status theo ngưỡng riêng
            new_status = d._status_from_signals(temp=new_temp, io_alarm=io_alarm, offline=offline)

            # Chỉ ghi khi có thay đổi ý nghĩa (dùng ngưỡng riêng)
            thr = d.temp_threshold or 620.0
            vals = {}

            if new_temp is not None:
                if (
                    d.temperature is None
                    or math.fabs((d.temperature or 0.0) - new_temp) > TEMP_EPS
                    or ((d.temperature or 10**9) < thr) != (new_temp < thr)
                ):
                    vals["temperature"] = new_temp

            if io_alarm != d.io_alarm:
                vals["io_alarm"] = io_alarm

            if new_status != d.status:
                vals["status"] = new_status

            if last_signal_at and (not d.last_signal_at or last_signal_at > d.last_signal_at):
                vals["last_signal_at"] = fields.Datetime.to_string(last_signal_at)

            if vals:
                vals["last_checked"] = fields.Datetime.now()

                # Bypass write() để điều phối notify thủ công (tránh double logic)
                super(sdm_Device, d).write(vals)

                # Notify dựa trên "trước → sau"
                if "status" in vals and new_status != old_status:
                    d._check_status_change(old_status, new_status)

                if "temperature" in vals:
                    code = d._check_temperature_transition(old_temp, vals["temperature"])
                    if code in ("temperature_low", "temperature_back_to_normal"):
                        d._send_temperature_notification(code)

                updated += 1

        return {"updated": updated, "offline": offline_count}

    # ========= Notification helpers =========
    def _send_temperature_notification(self, notification_type_code):
        if not self:
            return

        notification_name = {
            "temperature_low": "Nhiệt độ thấp",
            "temperature_back_to_normal": "Hồi phục nhiệt độ",
        }.get(notification_type_code, "Thông báo nhiệt độ")

        device_type = self[0].device_type_id

        notification_type = self.env["sdm.notification_type"].search(
            [("code", "=", notification_type_code)], limit=1
        )
        if not notification_type:
            notification_type = self.env["sdm.notification_type"].create(
                {"name": notification_name, "code": notification_type_code}
            )

        notification = self.env["sdm.notification"].search(
            [("device_type_id", "=", device_type.id), ("notification_type_id", "=", notification_type.id)],
            limit=1,
        )
        if not notification:
            notification = self.env["sdm.notification"].create(
                {
                    "name": notification_name,
                    "device_type_id": device_type.id,
                    "notification_type_id": notification_type.id,
                    "time_in_day": 8,
                    "interval_hours": 1,
                    "max_notice": 5,
                    "partner_ids": [(6, 0, self.env.ref("base.partner_admin").ids)],
                }
            )

        self._send_aggregated_notification(notification, self)

    def _check_status_change(self, old_status, new_status):
        _logger.info("Device %s status changed from %s to %s", self.name, old_status, new_status)
        notification_obj = self.env["sdm.notification"]

        notification_type_code = False

        if old_status == "not_available" and new_status != "not_available":
            notification_type_code = "device_operational"
        elif old_status != "not_available" and new_status == "not_available":
            notification_type_code = "device_not_operating"
        elif old_status == "normal" and new_status == "abnormal":
            notification_type_code = "underheating"
        elif old_status == "abnormal" and new_status == "normal":
            notification_type_code = "back_to_normal"
        elif old_status == "maintaince" and new_status == "normal":
            notification_type_code = "back_to_normal"
        elif old_status != "maintaince" and new_status == "maintaince":
            notification_type_code = "maintaince"

        if notification_type_code:
            notification_type = self.env["sdm.notification_type"].search(
                [("code", "=", notification_type_code)], limit=1
            )
            if not notification_type:
                notification_type = self.env["sdm.notification_type"].create(
                    {"name": notification_type_code.replace("_", " ").title(), "code": notification_type_code}
                )
                _logger.info("Created new Notification Type with code %s", notification_type_code)

            if notification_type_code in ("device_operational", "back_to_normal"):
                devices = self
            elif notification_type_code in ("device_not_operating", "underheating"):
                devices = self.search([("status", "=", new_status)])
            elif notification_type_code == "maintaince":
                devices = self.search([("status", "=", "maintaince")])
            else:
                devices = self

            notifications = notification_obj.search(
                [("device_type_id", "=", self.device_type_id.id), ("notification_type_id", "=", notification_type.id)]
            )
            if not notifications:
                default_notification = notification_obj.create(
                    {
                        "name": notification_type.name,
                        "device_type_id": self.device_type_id.id,
                        "notification_type_id": notification_type.id,
                        "time_in_day": 8,
                        "interval_hours": 1,
                        "max_notice": 5,
                        "partner_ids": [(6, 0, self.env.ref("base.partner_admin").ids)],
                    }
                )
                notifications = default_notification

            for notification in notifications:
                self._send_aggregated_notification(notification, devices)

    def _send_aggregated_notification(self, notification, devices):
        status_mapping = dict(self.fields_get(allfields=["status"])["status"]["selection"])

        device_list = [
            {
                "name": device.name,
                "code": device.code,
                "status": status_mapping.get(device.status, "N/A"),
                "last_checked": device.last_checked.strftime("%Y-%m-%d %H:%M:%S") if device.last_checked else "N/A",
                "temperature": device.temperature,
            }
            for device in devices
        ]
        subject = "Thông báo thiết bị"
        body_html = "<p>Thông tin thiết bị.</p>"

        if notification.notification_type_id.code == "all_devices_operational":
            subject = "Tất cả thiết bị đều hoạt động bình thường"
            body_html = """
                <p>Kính gửi Quý khách,</p>
                <p>Tất cả các thiết bị hiện đang hoạt động bình thường.</p>
                <p>Trân trọng,<br>Công ty của bạn</p>
            """
        elif notification.notification_type_id.code == "devices_not_available":
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

            subject = "Danh sách thiết bị không hoạt động"
            body_html = f"""
                <p>Kính gửi Quý khách,</p>
                <p>Các thiết bị sau hiện đang không hoạt động:</p>
                {device_list_html}
                <p>Vui lòng kiểm tra các thiết bị.</p>
                <p>Trân trọng,<br>Công ty của bạn</p>
            """
        elif notification.notification_type_id.code == "underheating":
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

            subject = "Danh sách thiết bị bất thường"
            body_html = f"""
                <p>Kính gửi Quý khách,</p>
                <p>Các thiết bị sau hiện đang ở trạng thái bất thường:</p>
                {device_list_html}
                <p>Vui lòng kiểm tra và xử lý.</p>
                <p>Trân trọng,<br>Công ty của bạn</p>
            """
        elif notification.notification_type_id.code == "back_to_normal":
            subject = "Thiết bị đã trở lại bình thường"
            device_list_html = """
            <table border="1" cellpadding="5" cellspacing="0">
                <tr>
                    <th>Tên thiết bị</th>
                    <th>Mã thiết bị</th>
                    <th>Trạng thái</th>
                    <th>Nhiệt độ</th>
                    <th>Kiểm tra lần cuối</th>
                </tr>
            """
            for device in device_list:
                device_list_html += f"""
                <tr>
                    <td>{device['name']}</td>
                    <td>{device['code']}</td>
                    <td>{device['status']}</td>
                    <td>{device['temperature']}</td>
                    <td>{device['last_checked']}</td>
                </tr>
                """
            device_list_html += "</table>"

            body_html = f"""
                <p>Kính gửi Quý khách,</p>
                <p>Các thiết bị sau đã trở lại trạng thái bình thường:</p>
                {device_list_html}
                <p>Trân trọng,<br>Công ty của bạn</p>
            """
        elif notification.notification_type_id.code == "temperature_low":
            subject = "Thiết bị có nhiệt độ thấp bất thường"
            device_list_html = """
                <table border="1" cellpadding="5" cellspacing="0">
                    <tr>
                        <th>Tên thiết bị</th>
                        <th>Mã thiết bị</th>
                        <th>Trạng thái</th>
                        <th>Nhiệt độ</th>
                        <th>Kiểm tra lần cuối</th>
                    </tr>
            """
            for device in device_list:
                device_list_html += f"""
                    <tr>
                        <td>{device['name']}</td>
                        <td>{device['code']}</td>
                        <td>{device['status']}</td>
                        <td>{device['temperature']}</td>
                        <td>{device['last_checked']}</td>
                    </tr>
                """
            device_list_html += "</table>"

            body_html = f"""
                <p>Kính gửi Quý khách,</p>
                <p>Thiết bị sau có nhiệt độ thấp dưới mức cho phép:</p>
                {device_list_html}
                <p>Vui lòng kiểm tra.<br>ご確認ください。</p>
                <p><i>Lưu ý: Đây là email tự động vui lòng không phản hồi qua email này<br>
                ご注意：これは自動送信メールです。このメールに返信しないでください。</i></p>
            """
        elif notification.notification_type_id.code == "maintaince":
            subject = "Cảnh báo thiết bị mất điện"
            device_list_html = """
                <table border="1" cellpadding="5" cellspacing="0">
                    <tr>
                        <th>Tên thiết bị</th>
                        <th>Mã thiết bị</th>
                        <th>Trạng thái</th>
                        <th>Thời gian mất điện</th>
                        <th>Kiểm tra lần cuối</th>
                    </tr>
            """
            now = fields.Datetime.now()
            for device in device_list:
                last_checked = (
                    datetime.strptime(device["last_checked"], "%Y-%m-%d %H:%M:%S")
                    if device["last_checked"] != "N/A"
                    else now
                )
                lost_duration = now - last_checked
                lost_duration_str = f"{int(lost_duration.total_seconds() // 3600)} giờ {(lost_duration.total_seconds() % 3600) // 60:.0f} phút"

                device_list_html += f"""
                    <tr>
                        <td>{device['name']}</td>
                        <td>{device['code']}</td>
                        <td>{device['status']}</td>
                        <td>{lost_duration_str}</td>
                        <td>{device['last_checked']}</td>
                    </tr>
                """
            device_list_html += "</table>"

            body_html = f"""
                <p>Kính gửi Quý khách,</p>
                <p>Các thiết bị sau đã mất điện trong khoảng thời gian dài:</p>
                {device_list_html}
                <p>Vui lòng kiểm tra.<br>ご確認ください。</p>
                <p><i>Lưu ý: Đây là email tự động vui lòng không phản hồi qua email này<br>
                ご注意：これは自動送信メールです。このメールに返信しないでください。</i></p>
            """
        elif notification.notification_type_id.code == "temperature_back_to_normal":
            subject = "Cảnh báo giảm nhiệt độ đã được dỡ bỏ đối với các lò nấu chảy"
            device_list_html = """
                <table border="1" cellpadding="5" cellspacing="0">
                    <tr>
                        <th>Tên thiết bị</th>
                        <th>Mã thiết bị</th>
                        <th>Trạng thái</th>
                        <th>Nhiệt độ</th>
                        <th>Kiểm tra lần cuối</th>
                    </tr>
            """
            for device in device_list:
                device_list_html += f"""
                    <tr>
                        <td>{device['name']}</td>
                        <td>{device['code']}</td>
                        <td>{device['status']}</td>
                        <td>{device['temperature']}</td>
                        <td>{device['last_checked']}</td>
                    </tr>
                """
            device_list_html += "</table>"

            body_html = f"""
                <p>Cảnh báo giảm nhiệt độ đã được dỡ bỏ đối với các lò nấu chảy sau: </p>
                <p>以下の溶解炉で規定温度低下警報が解除されました</p>
                {device_list_html}
                <p>Vui lòng kiểm tra.<br>ご確認ください。</p>
                <p><i>Lưu ý: Đây là email tự động vui lòng không phản hồi qua email này<br>
                ご注意：これは自動送信メールです。このメールに返信しないでください。</i></p>
            """

        recipient_emails = ",".join(notification.partner_ids.mapped("email"))
        email_from = "AIS Notification"

        if recipient_emails:
            if notification.notification_template_id:
                template = notification.notification_template_id

                body_html = template._render_template(
                    template.body_html, "sdm.device", [self.id], engine="qweb", add_context={"devices": device_list}
                )[self.id]

                subject = template._render_template(
                    template.subject, "sdm.device", [self.id], engine="qweb", add_context={"devices": device_list}
                )[self.id]

            mail_values = {
                "email_from": email_from,
                "subject": subject,
                "body_html": body_html,
                "email_to": recipient_emails,
            }
            self.env["mail.mail"].create(mail_values)

            self.env["sdm.notification_log"].create(
                {
                    "notification_id": notification.id,
                    "notification_type_id": notification.notification_type_id.id,
                    "time": fields.Datetime.now(),
                    "subject": subject,
                    "body": body_html,
                }
            )

    # ========= Cron: thông báo định kỳ (dùng ngưỡng riêng) =========
    @api.model
    def send_repeat_notifications(self):
        user_tz = self.env.user.tz or "UTC"
        local_tz = pytz.timezone(user_tz)

        current_time_local = datetime.now(local_tz)
        current_time_in_hours = current_time_local.hour + current_time_local.minute / 60.0
        now = fields.Datetime.now()

        notification_type_codes = [
            "all_devices_operational",
            "devices_not_available",
            "underheating",
            "temperature_low",
            "maintaince",
            "temperature_back_to_normal",
        ]

        for notification_type_code in notification_type_codes:
            notification_type = self.env["sdm.notification_type"].search([("code", "=", notification_type_code)], limit=1)
            if not notification_type:
                notification_type = self.env["sdm.notification_type"].create(
                    {
                        "name": "Tất cả thiết bị hoạt động bình thường"
                        if notification_type_code == "all_devices_operational"
                        else "Thiết bị không hoạt động"
                        if notification_type_code == "devices_not_available"
                        else "Thiết bị bất thường",
                        "code": notification_type_code,
                    }
                )

            notification = self.env["sdm.notification"].search([("notification_type_id", "=", notification_type.id)], limit=1)
            if not notification:
                notification = self.env["sdm.notification"].create(
                    {
                        "name": notification_type.name,
                        "notification_type_id": notification_type.id,
                        "time_in_day": 8.0,
                        "interval_hours": 1.0,
                        "max_notice": 5,
                        "partner_ids": [(6, 0, self.env.ref("base.partner_admin").ids)],
                    }
                )

            last_log_today = self.env["sdm.notification_log"].search(
                [
                    ("notification_id", "=", notification.id),
                    ("time", ">=", datetime.combine(current_time_local.date(), datetime.min.time()).astimezone(pytz.UTC)),
                    ("time", "<=", datetime.combine(current_time_local.date(), datetime.max.time()).astimezone(pytz.UTC)),
                ],
                limit=1,
            )

            time_difference = abs(current_time_in_hours - notification.time_in_day)

            if notification_type_code in ["all_devices_operational", "devices_not_available"]:
                if last_log_today:
                    continue

                if time_difference <= 0.084 or current_time_in_hours > notification.time_in_day:
                    devices = self.search([])
                    devices_not_available = devices.filtered(lambda d: d.status == "not_available")

                    if notification_type_code == "all_devices_operational" and not devices_not_available:
                        self._send_aggregated_notification(notification, devices)
                    elif notification_type_code == "devices_not_available" and devices_not_available:
                        self._send_aggregated_notification(notification, devices_not_available)

            elif notification_type_code == "underheating":
                devices_abnormal = self.search([("status", "=", "abnormal")])
                if devices_abnormal:
                    last_log = self.env["sdm.notification_log"].search(
                        [("notification_id", "=", notification.id)], order="time desc", limit=1
                    )
                    logs_today_count = self.env["sdm.notification_log"].search_count(
                        [
                            ("notification_id", "=", notification.id),
                            ("time", ">=", datetime.combine(current_time_local.date(), datetime.min.time()).astimezone(pytz.UTC)),
                            ("time", "<=", datetime.combine(current_time_local.date(), datetime.max.time()).astimezone(pytz.UTC)),
                        ]
                    )

                    can_send = False
                    if logs_today_count < notification.max_notice:
                        if not last_log:
                            can_send = True
                        else:
                            time_since_last_log = fields.Datetime.now() - last_log.time
                            if time_since_last_log >= timedelta(hours=notification.interval_hours):
                                can_send = True

                    if can_send:
                        self._send_aggregated_notification(notification, devices_abnormal)

            elif notification_type_code == "maintaince":
                devices_off = self.search([("status", "=", "maintaince")])

                for device in devices_off:
                    if not device.last_checked:
                        continue

                    time_diff = now - device.last_checked
                    hours_off = time_diff.total_seconds() / 3600.0

                    n = self.env["sdm.notification"].search(
                        [("notification_type_id", "=", notification_type.id), ("device_type_id", "=", device.device_type_id.id)],
                        limit=1,
                    )
                    if not n:
                        n = self.env["sdm.notification"].create(
                            {
                                "name": "Thiết bị mất điện",
                                "device_type_id": device.device_type_id.id,
                                "notification_type_id": notification_type.id,
                                "time_in_day": 8.0,
                                "interval_hours": 1.0,
                                "max_notice": 5,
                                "partner_ids": [(6, 0, self.env.ref("base.partner_admin").ids)],
                            }
                        )

                    logs_today_count = self.env["sdm.notification_log"].search_count(
                        [
                            ("notification_id", "=", n.id),
                            ("time", ">=", datetime.combine(current_time_local.date(), datetime.min.time()).astimezone(pytz.UTC)),
                            ("time", "<=", datetime.combine(current_time_local.date(), datetime.max.time()).astimezone(pytz.UTC)),
                        ]
                    )

                    last_log = self.env["sdm.notification_log"].search([("notification_id", "=", n.id)], order="time desc", limit=1)

                    can_send = False
                    if logs_today_count < n.max_notice:
                        if not last_log:
                            can_send = True
                        else:
                            time_since_last_log = now - last_log.time
                            if time_since_last_log >= timedelta(hours=n.interval_hours):
                                can_send = True

                    if can_send and hours_off >= n.interval_hours:
                        self._send_aggregated_notification(n, device)

            elif notification_type_code == "temperature_low":
                # Không hardcode 620 — dùng cờ is_below_threshold (ngưỡng riêng từng thiết bị)
                devices_low_temp = self.search([("status", "!=", "maintaince"), ("is_below_threshold", "=", True)])
                if devices_low_temp:
                    last_log = self.env["sdm.notification_log"].search(
                        [("notification_id", "=", notification.id)], order="time desc", limit=1
                    )
                    logs_today_count = self.env["sdm.notification_log"].search_count(
                        [
                            ("notification_id", "=", notification.id),
                            ("time", ">=", datetime.combine(current_time_local.date(), datetime.min.time()).astimezone(pytz.UTC)),
                            ("time", "<=", datetime.combine(current_time_local.date(), datetime.max.time()).astimezone(pytz.UTC)),
                        ]
                    )

                    can_send = False
                    if logs_today_count < notification.max_notice:
                        if not last_log:
                            can_send = True
                        else:
                            time_since_last_log = fields.Datetime.now() - last_log.time
                            if time_since_last_log >= timedelta(hours=notification.interval_hours):
                                can_send = True

                    if can_send:
                        self._send_aggregated_notification(notification, devices_low_temp)

            elif notification_type_code == "temperature_back_to_normal":
                # “Trở lại bình thường” = không còn dưới ngưỡng (và không ở maintenance)
                devices_back_to_normal = self.search(
                    [("status", "!=", "maintaince"), ("is_below_threshold", "=", False), ("temperature", "!=", False)]
                )
                if devices_back_to_normal:
                    logs_today_count = self.env["sdm.notification_log"].search_count(
                        [
                            ("notification_id", "=", notification.id),
                            ("time", ">=", datetime.combine(current_time_local.date(), datetime.min.time()).astimezone(pytz.UTC)),
                            ("time", "<=", datetime.combine(current_time_local.date(), datetime.max.time()).astimezone(pytz.UTC)),
                        ]
                    )
                    last_log = self.env["sdm.notification_log"].search(
                        [("notification_id", "=", notification.id)], order="time desc", limit=1
                    )

                    can_send = False
                    if logs_today_count < notification.max_notice:
                        if not last_log:
                            can_send = True
                        else:
                            time_since_last_log = now - last_log.time
                            if time_since_last_log >= timedelta(hours=notification.interval_hours):
                                can_send = True

                    if can_send:
                        self._send_aggregated_notification(notification, devices_back_to_normal)

    # ========= Điều khiển thủ công =========
    def change_device_status(self, device_id, type):
        device = self.browse(device_id)
        if not device.exists():
            raise UserError(_("Thiết bị không tồn tại."))

        if type == "on":
            if device.status == "maintaince":
                device.write({"status": "normal", "last_checked": fields.Datetime.now()})
                _logger.info("Device %s đã được bật lại", device.name)
            else:
                raise UserError(_("Thiết bị không ở trạng thái tắt."))
        elif type == "maintaince":
            if device.status != "maintaince":
                device.write({"status": "maintaince", "last_checked": fields.Datetime.now()})
                _logger.info("Device %s đã được tắt", device.name)
            else:
                raise UserError(_("Thiết bị đã ở trạng thái tắt."))
        else:
            raise UserError(_("Loại trạng thái không hợp lệ. Vui lòng chọn 'on' hoặc 'maintaince'."))


# =========================
#  Notification Models
# =========================
class sdm_NotificationType(models.Model):
    _name = "sdm.notification_type"
    _description = "Notification Type"

    name = fields.Char(string="Name")
    code = fields.Char(string="Code", index=True)
    notification_ids = fields.One2many("sdm.notification", "notification_type_id")


class sdm_Notification(models.Model):
    _name = "sdm.notification"
    _description = "Notification"

    name = fields.Char(string="Name")
    device_type_id = fields.Many2one("sdm.device_type", string="Device Type", index=True)
    notification_type_id = fields.Many2one("sdm.notification_type", string="Notification Type", index=True)
    time_in_day = fields.Float(string="Time in day")
    interval_hours = fields.Float(string="Interval Hours")
    max_notice = fields.Integer(string="Max Notice")
    notification_template_id = fields.Many2one("mail.template", string="Notification Template")
    partner_ids = fields.Many2many("res.partner", string="Partner")
    model_id = fields.Many2one("ir.model", string="Model", compute="_compute_model_id", store=True)

    @api.depends("name")
    def _compute_model_id(self):
        for record in self:
            record.model_id = self.env["ir.model"].search([("model", "=", "sdm.device")], limit=1).id


class sdm_NotificationLog(models.Model):
    _name = "sdm.notification_log"
    _rec_name = "notification_id"
    _description = "Notification Log"

    notification_id = fields.Many2one("sdm.notification", string="Notification")
    device_id = fields.Many2one("sdm.device", string="Device")
    notification_type_id = fields.Many2one("sdm.notification_type", string="Notification Type")
    time = fields.Datetime(string="Time", index=True)
    subject = fields.Char(string="Subject")
    body = fields.Html(string="Body")
