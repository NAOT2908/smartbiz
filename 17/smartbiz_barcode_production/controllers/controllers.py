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


