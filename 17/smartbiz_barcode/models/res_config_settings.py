# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models, SUPERUSER_ID, _
from odoo.exceptions import UserError


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'
    
    module_smartbiz_barcode = fields.Boolean("SmartBiz Barcode", group="base.group_user,base.group_portal")
    module_smartbiz_barcode_stock = fields.Boolean("Barcode Stock", group="base.group_user,base.group_portal")
    module_smartbiz_barcode_production = fields.Boolean("Barcode Production Order", group="base.group_user,base.group_portal")
    module_smartbiz_barcode_workorder = fields.Boolean("Barcode Workorder", group="base.group_user,base.group_portal")
    module_smartbiz_workorder_dashboard = fields.Boolean("Workorder Dashboard", group="base.group_user,base.group_portal")
    
    show_smartbiz_barcode_stock = fields.Boolean("Show SmartBiz Barcode", group="base.group_user,base.group_portal")
    show_smartbiz_barcode_production = fields.Boolean("Show SmartBiz Production Order", group="base.group_user,base.group_portal")
    show_smartbiz_barcode_workorder = fields.Boolean("Show SmartBiz Workorder", group="base.group_user,base.group_portal")
    
    
    