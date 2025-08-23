from odoo.addons.web.controllers.main import Home
import odoo
from odoo.http import request, serialize_exception
from odoo.tools.translate import _
from odoo import http
import logging
import base64
import json
import unicodedata

class HomeRedirect(Home):

    @http.route()
    def web_client(self, s_action=None, **kw):
        user = request.env.user
        if user.has_group('smartbiz_hr_app.group_hr_portal'):
            return request.redirect('/web#action=smartbiz_hr_action')
        return super().web_client(s_action, **kw)

    def _login_redirect(self, uid, redirect=None):
        user = request.env['res.users'].sudo().browse(uid)
        if user.has_group('smartbiz_hr_app.group_hr_portal'):
            # Lấy action và menu theo xml_id
            action = request.env.ref('smartbiz_hr_app.smartbiz_hr_action')
            menu = request.env.ref('smartbiz_hr_app.menu_smartbiz_hr_interface')
            redirect = f'/web#action={action.id}&menu_id={menu.id}'
        return super()._login_redirect(uid, redirect=redirect)
