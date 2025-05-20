# -*- coding: utf-8 -*-
{
    'name': "accountant_reconsile",

    'summary': "Short (1 phrase/line) summary of the module's purpose",

    'description': """
        Install this module to use lvm functionality in the reconsile menu in enterprise accounting module.
    """,

    'author': "My Company",
    'website': "https://www.yourcompany.com",

    # Categories can be used to filter modules in modules listing
    # Check https://github.com/odoo/odoo/blob/15.0/odoo/addons/base/data/ir_module_category_data.xml
    # for the full list
    'category': 'Uncategorized',
    'version': '17.0.1.0.0',

    # any module necessary for this one to work correctly
    'depends': ['ks_list_view_manager'],

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
            'accountant_reconsile/static/src/xml/reconsile_button.xml',
	  ]
    },
}

