import odoo
from odoo.http import request, serialize_exception
from odoo.tools.translate import _
from odoo import http
import logging
import base64
import json
import unicodedata



_logger = logging.getLogger(__name__)


class ServerList(http.Controller):
    @http.route('/server_list', auth='none')
    def server_list(self):
        response = {"result": [{"name": "PROD", "url": "https://erp.sbiz.vn", "db": "erp.sbiz.vn"},
                               {"name": "DEV", "url": "https://dev9.sbiz.vn", "db": "dev9.sbiz.vn"}]}
        return json.dumps(response)

class Upload(http.Controller):
    @http.route('/smartbiz/upload_attachment', type='http', auth="user", csrf=False)
    def test(self, model, id, ufile):
        files = request.httprequest.files.getlist('ufile')
        Model = request.env['ir.attachment']
        args = []
        for ufile in files:
            filename = ufile.filename
            if request.httprequest.user_agent.browser == 'safari':
                # Safari sends NFD UTF-8 (where é is composed by 'e' and [accent])
                # we need to send it the same stuff, otherwise it'll fail
                filename = unicodedata.normalize('NFD', ufile.filename)
            try:
                attachment = Model.create({
                 'name': filename,
                 'datas': base64.encodestring(ufile.read()),
                 'res_model': model,
                 'res_id': int(id)
                })
                attachment._post_add_create()
            except Exception:
                args.append({'error': _("Something horrible happened")})
                _logger.exception("Fail to upload attachment %s" % ufile.filename)
            else:
                args.append({
                    'filename': filename,
                    'mimetype': ufile.content_type,
                    'id': attachment.id,
                    'size': attachment.file_size
                })
        return json.dumps(args)

