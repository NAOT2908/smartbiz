/** @odoo-module **/
import { SearchView } from "@ks_list_view_manager/component/search_view";
import {AccountMoveUploadListRenderer} from "@account/components/bills_upload/bills_upload";
import {ExpenseListRenderer} from "@hr_expense/views/list";
import {ExpenseDashboardListRenderer} from"@hr_expense/views/list";
import {PurchaseDashBoardRenderer} from "@purchase/views/purchase_listview";

  AccountMoveUploadListRenderer.components = {...AccountMoveUploadListRenderer.components,SearchView};
  ExpenseListRenderer.components = {...ExpenseListRenderer.components,SearchView};
  ExpenseDashboardListRenderer.components = {...ExpenseDashboardListRenderer.components,SearchView};
  PurchaseDashBoardRenderer.components = {...PurchaseDashBoardRenderer.components,SearchView};
