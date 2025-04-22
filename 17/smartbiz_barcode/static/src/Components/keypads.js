/** @odoo-module **/
import { Component, EventBus, onPatched, onWillStart, useState, useSubEnv, xml } from "@odoo/owl";
import { registry } from "@web/core/registry";

export class KeyPads extends Component {
  setup() {
    this.state  = useState({
      quantity: '0',
    })
    if (this.props.data.quantity)
    {
      this.state.quantity = this.props.data.quantity.toString();
    }
  }
  
  keyClick = (option) => {
    option = option.toString();
    
    if (option == "DEL") {
      this.state.quantity = "0"; // Hoặc có thể xóa ký tự
    } 
    else if (option == "C") {
      var string = this.state.quantity;
      this.state.quantity = string.substring(0,string.length - 1);
    } 
    else if (option.includes("++")) {
      this.state.quantity =  this.props.data.remain_quantity?.toString();
    } 
    else if (option.includes("+")) {
      this.state.quantity = (parseFloat(this.state.quantity) + 1).toString();
    } 
    else if (option.includes("-")) {
      this.state.quantity = (parseFloat(this.state.quantity) - 1).toString();
    } 
    else {
      if (!(this.state.quantity.toString().includes(".") && option == "."))
      {
        if (this.state.quantity != '0')
          this.state.quantity = this.state.quantity + option;
        else 
          this.state.quantity = option;
      }  
    }
  };
  confirm(){
    this.props.closeKeypad(this.props.data,this.state.quantity)
  }
  cancel(){
    this.props.closeKeypad(this.props.data,'cancel')
  }
}
KeyPads.props = ["data", "closeKeypad"];
KeyPads.template = "smartbiz_barcode.keypads";
