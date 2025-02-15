from collections import defaultdict
import json
from odoo import http, _
from odoo.http import request
from odoo.exceptions import UserError
from odoo.osv import expression
from odoo.tools import pdf, split_every
from odoo.tools.misc import file_open
import base64,pytz,logging
_logger = logging.getLogger(__name__)



class CustomRPC(http.Controller):
    @http.route('/custom/get_permissions', type='json', auth='user')
    def get_permissions(self):
        user = request.env.user
        return {
            'show_barcode_stock': user.show_smartbiz_barcode_stock,
            'show_barcode_production': user.show_smartbiz_barcode_production,
            'show_barcode_workorder': user.show_smartbiz_barcode_workorder,
        }
    @http.route('/common_route', type='json', auth='user')
    def handle_common_route(self):
        # Logic cho nhiều addons
        return {'message': 'Hello from common controller'}