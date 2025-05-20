/** @odoo-module **/

import { registry } from "@web/core/registry";
const { Component, useState} = owl;
import { Dropdown } from "@web/core/dropdown/dropdown";
import { DropdownItem } from "@web/core/dropdown/dropdown_item";


export class KsSelectionField extends Component {
        setup(){
            var self = this.props;
            this.currentSelection = this.props.record.data?.data_source
            this.state = useState({
                currentSelection: this.currentSelection
            });
            this.defaultSelections = [
                ['odoo', 'Odoo'],
                ['excel', 'Excel'],
                ['csv', 'CSV'],
                ['external_api', 'External API']
            ]

        }

        onDropdownItemSelect(selection){
            this.state.currentSelection = selection[1]
            this.currentSelection = selection[1]
            this.props.record.update({ [this.props.name]: selection[0]})
        }

        get selections(){
            let selections = this.props.record?._config?.fields?.data_source?.selection
            return selections ? selections : this.defaultSelections
        }

    }

KsSelectionField.template="ks_dashboard_selection_field_widget";
KsSelectionField.components = { Dropdown, DropdownItem }

export const KsSelectionFieldDef = {
    component:  KsSelectionField,
    supportedTypes: ["selection"],
    supportedOptions: [
        {
            label: "Selection Domain",
            name: "selection_domain",
            type: "Array",
        },
    ],
    extractProps: ({ attrs, options }) => ({
        selection_domain: options.selection_domain,
    }),
};
registry.category("fields").add('ks_dashboard_selection_field', KsSelectionFieldDef);