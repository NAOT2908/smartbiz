/** @odoo-module **/
import { Component, EventBus, onPatched, onWillStart, useState, useSubEnv, xml } from "@odoo/owl";
import { registry } from "@web/core/registry";

export class KeyPads extends Component {
  setup() {}
  keyClick(option) {
    // console.log(this);
    this.props.keyClick(option);
  }
}
KeyPads.props = ["detailMoveLine?", "keyClick?", "keyPadTitle?", "currentQuantityField"];
KeyPads.template = "smartbiz_barcode.keypads";
