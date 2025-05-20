from markupsafe import Markup
from odoo import models, fields, _


class ChatChannel(models.Model):
    _inherit = 'discuss.channel'

    ks_dashboard_board_id = fields.Many2one('ks_dashboard_ninja.board')
    ks_dashboard_item_id = fields.Many2one('ks_dashboard_ninja.item')

    def ks_chat_wizard_channel_id(self, **kwargs):
        item_id = kwargs.get('item_id')
        dashboard_id = kwargs.get('dashboard_id')
        item_name = kwargs.get('item_name')
        dashboard_name = kwargs.get('dashboard_name')

        channel = self.search([('ks_dashboard_item_id', '=', item_id)], limit=1)

        if not channel:
            users = self.env['res.users'].search([('groups_id', 'in', self.env.ref('base.group_user').ids)]).mapped('partner_id.id')

            channel = self.create({
                'name': f"{dashboard_name} - {item_name}",
                'ks_dashboard_board_id': dashboard_id,
                'ks_dashboard_item_id': item_id,
                'channel_member_ids': [(0, 0, {'partner_id': partner_id}) for partner_id in users]
            })

            notification = Markup('<div class="o_mail_notification">%s</div>') % _("created this channel.")
            channel.message_post(body=notification, message_type="notification", subtype_xmlid="mail.mt_comment")
            channel_info = channel._channel_info()[0]
            self.env['bus.bus']._sendone(self.env.user.partner_id, 'mail.record/insert', {"Thread": channel_info})

        return channel.id if channel else None
