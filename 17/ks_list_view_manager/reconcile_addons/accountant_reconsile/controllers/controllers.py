# -*- coding: utf-8 -*-
# from odoo import http


# class AccountantReconsile(http.Controller):
#     @http.route('/accountant_reconsile/accountant_reconsile', auth='public')
#     def index(self, **kw):
#         return "Hello, world"

#     @http.route('/accountant_reconsile/accountant_reconsile/objects', auth='public')
#     def list(self, **kw):
#         return http.request.render('accountant_reconsile.listing', {
#             'root': '/accountant_reconsile/accountant_reconsile',
#             'objects': http.request.env['accountant_reconsile.accountant_reconsile'].search([]),
#         })

#     @http.route('/accountant_reconsile/accountant_reconsile/objects/<model("accountant_reconsile.accountant_reconsile"):obj>', auth='public')
#     def object(self, obj, **kw):
#         return http.request.render('accountant_reconsile.object', {
#             'object': obj
#         })

