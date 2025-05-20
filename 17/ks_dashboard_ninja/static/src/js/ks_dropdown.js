/** @odoo-module **/

import { Component, xml, useEffect } from "@odoo/owl";
import { Select } from "@web/core/tree_editor/tree_editor_components";
import { Dropdown } from "@web/core/dropdown/dropdown";
import { DropdownItem } from "@web/core/dropdown/dropdown_item";


export class KsDropDown extends Select{
    setup(){
        super.setup();
    }

    deserialize(value){
        return JSON.parse(value);
    }
}

KsDropDown.template = xml`<Dropdown class="'o_input pe-3 text-truncate'">
                                <t t-set-slot="toggler">
                                    <button class="text-decoration-none" href="#" role="button" aria-expanded="false">
                                        <t t-out="props.activeOption"/>
                                    </button>
                                </t>
                                <DropdownItem
                                    t-foreach="props.options"
                                    t-as="option"
                                    t-key="serialize(option[0])"
                                    class="{ '': true }"
                                    t-esc="option[1]"
                                    dataset="{ value : serialize(option[0]) }"
                                    onSelected="() => this.props.update(this.deserialize(serialize(option[0])))"
                                  />
                            </Dropdown>`

KsDropDown.components = { Dropdown, DropdownItem }

KsDropDown.props = [ ...Select.props, "activeOption"]




