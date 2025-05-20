# -*- coding: utf-8 -*-
# from odoo import http


# class AccountLvm(http.Controller):
#     @http.route('/account_lvm/account_lvm', auth='public')
#     def index(self, **kw):
#         return "Hello, world"

#     @http.route('/account_lvm/account_lvm/objects', auth='public')
#     def list(self, **kw):
#         return http.request.render('account_lvm.listing', {
#             'root': '/account_lvm/account_lvm',
#             'objects': http.request.env['account_lvm.account_lvm'].search([]),
#         })

#     @http.route('/account_lvm/account_lvm/objects/<model("account_lvm.account_lvm"):obj>', auth='public')
#     def object(self, obj, **kw):
#         return http.request.render('account_lvm.object', {
#             'object': obj
#         })

