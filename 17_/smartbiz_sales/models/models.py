# -*- coding: utf-8 -*-

from odoo import models, fields, api, tools
import logging

_logger = logging.getLogger(__name__)

class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'
    sale_order_id = fields.Many2one('sale.order', string='Sale Order')


class SalesReport(models.Model):
    _name = "sales.report"
    _auto = False
    _description = "Report"
    
    order_id = fields.Many2one('sale.order', string='Order', readonly=True)
    customer_id = fields.Many2one('res.partner', string='Customer')
    date = fields.Datetime(string='Date')
    team_id = fields.Many2one('crm.team', string='Sales Team')
    user_id = fields.Many2one('res.users', string='Salesperson')
    revenue = fields.Float(string='Revenue')
    amount_untaxed = fields.Float(string='Amount Untaxed')
    cost_of_goods_sold = fields.Float(string='Cost of Goods Sold')
    purchase_expenses = fields.Float(string='Purchase Expenses')
    purchase_expenses_untaxed = fields.Float(string='Purchase Expenses Untaxed')
    other_expenses = fields.Float(string='Other Expenses')
    total_revenue = fields.Float(string='Total Revenue')
    total_expenses = fields.Float(string='Total Expenses')
    net_profit = fields.Float(string='Net Profit')
    net_profit_untaxed = fields.Float(string='Net Profit Untaxed')
    order_status = fields.Selection([('draft', 'Báo giá'), ('sent', 'Báo giá đã gửi'), ('sale', 'Đơn hàng'), ('done', 'Hoàn tất'), ('cancel', 'Hủy')], string='Order Status', readonly=True)
    invoice_status = fields.Selection([('upselling', 'Có cơ hội bán thêm'), ('invoiced', 'Đã xuất đủ hóa đơn'), ('to_invoice', 'Cần xuất hóa đơn'), ('no', 'Không cần xuất hóa đơn')], string='Invoice Status', readonly=True)
    payment_state = fields.Selection([('not_paid', 'Chưa thanh toán'), ('paid', 'Đã thanh toán'), ('in_payment', 'Đang thanh toán'), ('partial', 'Thanh toán một phần'), ('reversed', 'Đã đảo'), ('invoicing_legacy', 'App cũ')], string='Payment Status', readonly=True)

    def init(self):
        tools.drop_view_if_exists(self._cr, 'sales_report')
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW sales_report AS (
                WITH revenue_cte AS (
                    SELECT
                        so.id AS order_id,
                        SUM(sol.price_total) AS revenue,
                        SUM(sol.price_subtotal) AS amount_untaxed
                    FROM
                        sale_order so
                    JOIN
                        sale_order_line sol ON so.id = sol.order_id
                    GROUP BY
                        so.id
                ),
                cost_of_goods_sold_cte AS (
                    SELECT
                        so.id AS order_id,
                        SUM(svl.value) AS cost_of_goods_sold
                    FROM
                        sale_order so
                    JOIN
                        sale_order_line sol ON so.id = sol.order_id
                    JOIN
                        stock_move sm ON sm.sale_line_id = sol.id
                    JOIN
                        stock_valuation_layer svl ON svl.stock_move_id = sm.id
                    WHERE
                        svl.quantity < 0
                    GROUP BY
                        so.id
                ),
                purchase_expenses_cte AS (
                    SELECT
                        so.id AS order_id,
                        SUM(pol.price_total) AS purchase_expenses,
                        SUM(pol.price_subtotal) AS purchase_expenses_untaxed
                    FROM
                        sale_order so
                    JOIN
                        sale_order_line sol ON so.id = sol.order_id
                    JOIN
                        purchase_order_line pol ON pol.sale_line_id = sol.id
                    JOIN
                        purchase_order po ON po.id = pol.order_id
                    GROUP BY
                        so.id
                ),
                other_expenses_cte AS (
                    SELECT
                        aml.sale_order_id AS order_id,
                        SUM(aml.debit + aml.credit) AS other_expenses
                    FROM
                        account_move_line aml
                    WHERE
                        aml.sale_order_id IS NOT NULL
                        AND aml.product_id IS NULL
                    GROUP BY
                        aml.sale_order_id
                ),
                payment_state_cte AS (
                    SELECT
                        so.id AS order_id,
                        MAX(am.payment_state) AS payment_state
                    FROM
                        sale_order so
                    JOIN
                        account_move am ON am.invoice_origin = so.name
                    GROUP BY
                        so.id
                )
                SELECT
                    ROW_NUMBER() OVER() as id,
                    so.id AS order_id,
                    so.partner_id AS customer_id,
                    so.date_order AS date,
                    COALESCE(rc.revenue, 0) AS revenue,
                    COALESCE(rc.amount_untaxed, 0) AS amount_untaxed,
                    COALESCE(-cogs.cost_of_goods_sold, 0) AS cost_of_goods_sold,
                    COALESCE(pe.purchase_expenses, 0) AS purchase_expenses,
                    COALESCE(pe.purchase_expenses_untaxed, 0) AS purchase_expenses_untaxed,
                    COALESCE(oe.other_expenses, 0) AS other_expenses,
                    COALESCE(rc.revenue, 0) AS total_revenue,
                    (COALESCE(-cogs.cost_of_goods_sold, 0) + COALESCE(pe.purchase_expenses, 0) + COALESCE(oe.other_expenses, 0)) AS total_expenses,
                    (COALESCE(rc.revenue, 0) - (COALESCE(-cogs.cost_of_goods_sold, 0) + COALESCE(pe.purchase_expenses, 0) + COALESCE(oe.other_expenses, 0))) AS net_profit,
                    (COALESCE(rc.amount_untaxed, 0) - (COALESCE(-cogs.cost_of_goods_sold, 0) + COALESCE(pe.purchase_expenses_untaxed, 0) + COALESCE(oe.other_expenses, 0))) AS net_profit_untaxed,
                    so.team_id AS team_id,
                    so.user_id AS user_id,
                    so.state AS order_status,
                    so.invoice_status AS invoice_status,
                    COALESCE(ps.payment_state, 'not_paid') AS payment_state
                FROM
                    sale_order so
                LEFT JOIN
                    revenue_cte rc ON so.id = rc.order_id
                LEFT JOIN
                    cost_of_goods_sold_cte cogs ON so.id = cogs.order_id
                LEFT JOIN
                    purchase_expenses_cte pe ON so.id = pe.order_id
                LEFT JOIN
                    other_expenses_cte oe ON so.id = oe.order_id
                LEFT JOIN
                    payment_state_cte ps ON so.id = ps.order_id
            )
        """)
