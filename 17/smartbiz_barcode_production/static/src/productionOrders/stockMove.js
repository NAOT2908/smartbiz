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

export class Moves extends Component {
  static template = "StockMoves";
  static props = ["stockMoves", "selectedMove", "moveClick", "selectItem"];
  setup() {
    this.state = useState({
      stockMoves: this.props.stockMoves,
      
    });

  }

  getClass(item) {

    let cl = "s_move-line";
    if(item.state == 'done')
    {
      cl += " bg-green";
    }
    else 
    {
      if(item.picked)
      {
        if(item.quantity > item.product_uom_qty)
          {
            cl += " bg-red";
          }
          else if(item.quantity < item.product_uom_qty)
          {
            cl += " bg-yellow";
          }
          else if(item.quantity == item.product_uom_qty) 
          {
            cl += " bg-blue";
          }
      }
      else
      {

      }

      
    }
    
    return cl;
  }
}

export class MoveLineEdit extends Component {
    static template = "MoveLineEdit";
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

export class MoveLines extends Component {
    static template = "StockMoveLines";
    static props = [
      "moveLines",
      "selectedMoveLine",
      "moveLineClick",
      "deleteMoveLine",
      "print",
    ];
    setup() {
      this.state = useState({
        moveLines: this.props.moveLines,
        selectedMoveLine: this.props.selectedMoveLine,
      });
    }
    scrollToSelectedMove() {
      const selectedElement = document.querySelector(`[data-id="${this.state.selectedMoveLine}"]`);
      if (selectedElement) {
          selectedElement.scrollIntoView({
              behavior: "smooth", // Hiệu ứng cuộn mượt
              block: "center",    // Căn giữa màn hình
          });
      }
    }
    getClass(line) {
      // console.log(line)
      let cl = "s_move-line";
      if (line.state === "done") {
        cl += " bg-green";
      } else 
      {
        if (line.picked) {
          cl += " bg-blue";
        }
      }
      
      this.scrollToSelectedMove();
      return cl;
    }
  }

