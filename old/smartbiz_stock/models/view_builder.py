# -*- coding: utf-8 -*-
from odoo import api, fields as _f, tools, models
import uuid, textwrap, logging
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

PREFIX = "x_"           # mọi trường động phải bắt đầu bằng x_

class NXTDynamicBuilder(models.AbstractModel):
    """Mixin chứa toàn bộ logic sinh VIEW, đồng bộ field, mở rộng tree/pivot."""
    _name = "smartbiz_stock.nxt_builder"
    _description = "Mixin build NXT view"

    # ......................................................................
    # PUBLIC: build(view) – gọi từ wizard
    # ......................................................................
