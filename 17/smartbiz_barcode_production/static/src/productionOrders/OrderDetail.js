/** @odoo-module **/
import { registry } from "@web/core/registry";
import {
  Component,
  EventBus,
  onPatched,
  onWillStart,
  useState,
  useSubEnv,
  xml,
} from "@odoo/owl";
import { useService, useBus, useHistory } from "@web/core/utils/hooks";
import * as BarcodeScanner from "@web/webclient/barcode/barcode_scanner";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { View } from "@web/views/view";
// import { ManualBarcodeScanner } from "@smartbiz_barcode/Components/manual_barcode";
import { url } from "@web/core/utils/urls";
import { utils as uiUtils } from "@web/core/ui/ui_service";

export class OrderDetail extends Component {
    static template = "OrderDetail";
    static props = [
      "order",
      "detailMoveLine",
      "quantity",
      "locations",
      "lots",
      "selectedButton",
      "validate",
      "handleButtonClick",
      "saveOrder",
      "packMoveLine",
      "print_lines",
      "createLot",
      "editQuantityClick",
      "openSelector",
      "clearResultPackage",
      "buttonStatus",
      "resetDetailMoveLine"
    ];
    setup() {
      this.state = useState({
        order: this.props.order,
        detailMoveLine: this.props.detailMoveLine,
        quantity: this.props.quantity,
        locations: this.props.locations,
        lots: this.props.lots,
        selectedButton: this.props.selectedButton,
      });
      // console.log(this.props.detailMoveLine)
      
    }
    
  }

