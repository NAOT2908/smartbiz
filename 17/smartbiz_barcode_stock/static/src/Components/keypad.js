/** @odoo-module **/
import { Component, EventBus, onPatched, onWillStart, useState, useSubEnv,xml } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";
export class KeyPad extends Component{
    
    setup() {
      this._t = _t;
    }
    keyClick(option)
      {
        console.log(this.props.detailMoveLine)
        this.props.keyClick(option);                
      }
      
    
}
KeyPad.props = ['detailMoveLine?','keyClick?'];
KeyPad.template = 'smartbiz_barcode.keypad'
KeyPad.components = { }



      