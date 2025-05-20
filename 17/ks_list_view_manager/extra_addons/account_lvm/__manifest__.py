# -*- coding: utf-8 -*-
{
    'name': "account_lvm",

    'summary': "Short (1 phrase/line) summary of the module's purpose",

    'description': """
        Install this module to use list view manager functionality in  account,purchase,stock and expense module.
    """,

    'author': "My Company",
    'website': "https://www.yourcompany.com",

    # Categories can be used to filter modules in modules listing
    # Check https://github.com/odoo/odoo/blob/15.0/odoo/addons/base/data/ir_module_category_data.xml
    # for the full list
    'category': 'Uncategorized',
    'version': '17.0.1.0.0',

    # any module necessary for this one to work correctly
    'depends': ['ks_list_view_manager','account','purchase','hr_expense','stock'],

    # always loaded
    'data': [
        # 'security/ir.model.access.csv',
        'views/views.xml',
        'views/templates.xml',
    ],
    # only loaded in demonstration mode
    'demo': [
        'demo/demo.xml',
    ],

    'assets': {'web.assets_backend':
		[
			'account_lvm/static/src/js/account_lvm_render.js',
			'account_lvm/static/src/xml/account_lvm_button.xml',
			'account_lvm/static/src/xml/account_row.xml',
			'account_lvm/static/src/xml/account_search_view.xml',

	  ]
    },
}

