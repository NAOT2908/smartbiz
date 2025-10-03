/** @odoo-module **/
import { Component, useState } from "@odoo/owl";

export class EditQuantityModal extends Component {
    static template = "EditQuantityModal";
    static props = ['detailMoveLine', 'closeQuantityModal'];
    setup() {
        this.state = useState({
            // quantity: this.props.detailMoveLine.quantity,  
            expression: this.props.detailMoveLine.quantity || '', // Khởi tạo expression là chuỗi rỗng
            detailMoveLine: this.props.detailMoveLine,
        });
        // console.log(this.state.quantity)
    }

    keyClick = (option) => {
        option = option.toString();

        if (option == "cancel") {
            this.props.closeQuantityModal()
        }
        else if (option == "confirm") {
            this.props.closeQuantityModal()
        }
        else if (option == "DEL") {
            this.state.expression = '';
            this.state.detailMoveLine.quantity = '0';
        }
        else if (option == "C") {
            if (this.state.expression && this.state.expression.length > 0) {
                this.state.expression = this.state.expression.slice(0, -1);
                this.state.detailMoveLine.quantity = this.state.expression || '0';
            }
        }
        else if (option == "=") {
            try {
                // Chuyển x thành * cho phép nhân
                let expr = this.state.expression.replace(/x/g, '*');
                let result = eval(expr);
                this.state.detailMoveLine.quantity = result.toString();
                this.state.expression = result.toString();
            } catch {
                this.state.detailMoveLine.quantity = 'Error';
                this.state.expression = '';
            }
        }
        else {
            // Chỉ cho phép các ký tự số, ., +, -, x, /
            if ("0123456789.+-x/".includes(option)) {
                this.state.expression += option;
            }
            this.state.detailMoveLine.quantity = this.state.expression;
        }
    }
}
