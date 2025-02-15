# from collections import defaultdict
# import json
# from odoo import http, _
# from odoo.http import request
# from odoo.exceptions import UserError
# from odoo.osv import expression
# from odoo.tools import pdf, split_every
# from odoo.tools.misc import file_open
# import base64,pytz,logging
# _logger = logging.getLogger(__name__)

# class ComponentController(http.Controller):

#     @http.route('/get_attachment_url', type='json', auth='user')
#     def get_attachment_url(self, component_id):
#         # Lấy attachment liên kết với component
#         attachment = request.env['ir.attachment'].search([
#             ('res_model', '=', 'mrp.workorder'),  # Model của component
#             ('res_id', '=', component_id),  # ID của component
#         ], limit=1)
        
#         if attachment:
#             return {
#                 'url': f'/web/content/{attachment.id}/{attachment.name}',
#                 'name': attachment.name
#             }
#         return {'error': 'No attachment found'}
