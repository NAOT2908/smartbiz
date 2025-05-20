# -*- coding: utf-8 -*-

{
    'name': "VietTri Customizations",
    'summary': "VietTri Customizations",
    'description': "VietTri Customizations",
    'author': "SmartBiz",
    'website': "https://www.sbiz.vn",

    # Categories can be used to filter modules in modules listing
    'category': 'SmartBiz Apps',
    'license': 'Other proprietary',
    'version': '1.0',

    # Any module necessary for this one to work correctly
    'depends': [
        'base','smartbiz_stock',
        'mail',
    ],

    # always loaded
    'data': [
        'security/ir.model.access.csv',
        'views/views.xml',
    ],

    # 'assets': {
    #     'web.assets_backend': [
    #           'smartbiz_vtc/static/src/**/*.js',
    #           'smartbiz_vtc/static/src/**/*.scss',
    #           'smartbiz_vtc/static/src/**/*.xml',
    #      ],
    #     'web.assets_qweb': [
    #      ],
    #  },

    'qweb': [
    ],

    # only loaded in demonstration mode
    'demo': [
    ],

    # Application settings
    'installable': True,
    'application': True,
}
