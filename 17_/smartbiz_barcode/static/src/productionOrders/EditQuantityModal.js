/** @odoo-module **/
import { Component, useState } from "@odoo/owl";

export class EditQuantityModal extends Component {
    static template = "EditQuantityModal";
    static props = ['detailMoveLine', 'closeQuantityModal'];
    setup() {
        this.state = useState({
            quantity: 2,  // Dùng chuỗi để dễ dàng xử lý
            detailMoveLine: this.props.detailMoveLine,
        });
        console.log(this.state.quantity)
    }

    keyClick = (option) => {
        option = option.toString();
        
        if (!this.state.detailMoveLine.quantity) {
            this.state.detailMoveLine.quantity = 0
        }
        if (option == "cancel") {
            this.props.closeQuantityModal()
        }
        else if (option == "confirm") {
            this.props.closeQuantityModal()
        }
        else if (option == "DEL") {
            this.state.detailMoveLine.quantity = '0';
        }
        else if (option == "C") {
            var string = this.state.detailMoveLine.quantity.toString();

            this.state.detailMoveLine.quantity = string.substring(0, string.length - 1);
        }
        else if (option.includes('++')) {
            this.state.detailMoveLine.quantity = this.state.detailMoveLine.quantity_need.toString()
        }
        else if (option.includes('+')) {
            this.state.detailMoveLine.quantity = (parseFloat(this.state.detailMoveLine.quantity) + 1).toString();
        }
        else if (option.includes('-')) {
            this.state.detailMoveLine.quantity = (parseFloat(this.state.detailMoveLine.quantity) - 1).toString();
        }
        else {
            if (!(this.state.detailMoveLine.quantity.toString().includes('.') && option == '.'))
                if (this.state.detailMoveLine.quantity != 0){
                    this.state.detailMoveLine.quantity = this.state.detailMoveLine.quantity.toString() + option
                    // console.log(this.state.detailMoveLine.quantity)
                }
                else {

                    this.state.detailMoveLine.quantity = option
                }
                
        }
    }
}
