# -*- coding: utf-8 -*-

{
    'name': "SmartBiz Sales",
    'summary': "SmartBiz Sales",
    'description': "SmartBiz Sales",
    'author': "SmartBiz",
    'website': "https://www.sbiz.vn",

    # Categories can be used to filter modules in modules listing
    'category': 'SmartBiz Apps',
    'license': 'Other proprietary',
    'version': '1.0',

    # Any module necessary for this one to work correctly
    'depends': [
        'base','smartbiz','sale_purchase','account',
        'mail',
    ],

    # always loaded
    'data': [
        'security/securities.xml',
        'security/ir.model.access.csv',
        'views/views.xml',
        'report/report.xml',
        'report/report_templates.xml',
        'data/data.xml',
    ],

    'assets': {
        'web.assets_backend': [
              'smartbiz_sales/static/src/**/*.js',
              'smartbiz_sales/static/src/**/*.scss',
              'smartbiz_sales/static/src/**/*.xml',
         ],
        'web.assets_qweb': [
         ],
     },

    'qweb': [
    ],

    # only loaded in demonstration mode
    'demo': [
    ],

    # Application settings
    'installable': True,
    'application': True,
}
