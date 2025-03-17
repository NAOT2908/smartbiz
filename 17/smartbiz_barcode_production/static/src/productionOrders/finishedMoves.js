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
// import { ManualBarcodeScanner } from "@smartbiz_barcode/Components//manual_barcode";
import { url } from "@web/core/utils/urls";
import { utils as uiUtils } from "@web/core/ui/ui_service";


export class FinishedMoves extends Component {
    static template = "FinishedMoves";
    static props = ['finishedMoves', 'selectedFinished', 'finishedMoveClick', "selectItem"];
    setup() {
        this.state = useState({
            finishedMoves: this.props.finishedMoves,
            selectedFinished: this.props.selectedFinished,
            finishedMoveClick: this.props.finishedMoveClick,
        });
    }
    getClass(component) {
        console.log(component)
        let cl = " ";
        if(component.state == 'confirmed')
        {
          if (component.quantity == component.product_uom_qty) {
            cl += " bg-green";
          } else if (component.quantity <= component.product_uom_qty
          ) {
            cl += " bg-yellow";
          } else if (component.quantity >= component.product_uom_qty
          ) {
            cl += " bg-red";
          }
        }

        
        return cl;
      }
}