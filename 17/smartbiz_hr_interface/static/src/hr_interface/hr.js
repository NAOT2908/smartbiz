/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { COMMANDS } from "@barcodes/barcode_handlers";
import { registry } from "@web/core/registry";

import {
  Component,
  EventBus,
  onPatched,
  onWillStart,
  useState,
  useSubEnv,
  xml,
  useEnv,
  onWillUnmount,
  onMounted,
  useRef,
} from "@odoo/owl";
import { useService, useBus, useHistory } from "@web/core/utils/hooks";
import { loadJS } from "@web/core/assets";

export class HrInterface extends Component {
  static template = "smartbiz_hr_interface";
  static props = {
    action: { type: Object, optional: true },
    actionId: { type: Number, optional: true },
    className: { type: String, optional: true },
    globalState: { type: Object, optional: true }, // <-- thêm dòng này
  };

  setup() {
    this.state = useState({ sidebarVisible: false,
        view: "attendance",
     });
    this.rpc = useService("rpc");
    this.orm = useService("orm");
    this.notification = useService("notification");
    this.dialog = useService("dialog");
    this.action = useService("action");
    this.home = useService("home_menu");
    this.store = useService("mail.store");
    this.userService = useService("user");
    // Refs
    this.sidebarRef = useRef("sidebar");
    this.headerRef = useRef("header");
    this.mainRef = useRef("main");
    this.themeButtonRef = useRef("themeButton");
    this.sidebarLinksRef = useRef("sidebarLinks");

    onMounted(() => {
      const themeBtn = this.themeButtonRef.el;
      const sidebarLinks = this.sidebarLinksRef.el?.querySelectorAll("a");

      // ====== Theme Toggle ======
      const darkTheme = "dark-theme";
      const iconThemeSun = "fa-sun-o"; // Class cho icon mặt trời
      const iconThemeMoon = "fa-moon-o"; // Class cho icon mặt trăng
      const selectedTheme = localStorage.getItem("selected-theme");
      const selectedIcon = localStorage.getItem("selected-icon");

      const getCurrentTheme = () =>
        document.body.classList.contains(darkTheme) ? "dark" : "light";
      const getCurrentIcon = () =>
        themeBtn?.classList.contains(iconThemeMoon)
          ? iconThemeMoon
          : iconThemeSun;

      if (selectedTheme) {
        document.body.classList[selectedTheme === "dark" ? "add" : "remove"](
          darkTheme
        );
        themeBtn?.classList[selectedIcon === iconThemeMoon ? "add" : "remove"](
          iconThemeMoon
        ); // Thêm hoặc bỏ icon mặt trăng
        themeBtn?.classList[selectedIcon === iconThemeSun ? "add" : "remove"](
          iconThemeSun
        ); // Thêm hoặc bỏ icon mặt trời
      }

      themeBtn?.addEventListener("click", () => {
        document.body.classList.toggle(darkTheme);
        themeBtn.classList.toggle(iconThemeSun); // Toggle icon mặt trời
        themeBtn.classList.toggle(iconThemeMoon); // Toggle icon mặt trăng
        localStorage.setItem("selected-theme", getCurrentTheme());
        localStorage.setItem("selected-icon", getCurrentIcon());
      });

      // ====== Sidebar link active state ======
      sidebarLinks?.forEach((link) => {
        link.addEventListener("click", function () {
          sidebarLinks.forEach((l) => l.classList.remove("active-link"));
          this.classList.add("active-link");
        });
      });

      // ====== Hiện sidebar nếu màn hình >= 1150px ======
      if (window.innerWidth >= 1150) {
        this.state.sidebarVisible = true;
      }
    });
  }

  toggleSidebar() {
    this.state.sidebarVisible = !this.state.sidebarVisible;
  }

  changeTab(tab) {
    this.env.bus.trigger("changeTab", tab);
  }

}

registry.category("actions").add("smartbiz_hr_interface", HrInterface);
