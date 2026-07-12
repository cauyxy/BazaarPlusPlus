import { definePlugin } from "@decky/api";
import { staticClasses } from "@decky/ui";
import { FaStore } from "react-icons/fa";

import { PluginPanel } from "./features/installer/PluginPanel";

export default definePlugin(() => ({
  name: "BazaarPlusPlus",
  titleView: <div className={staticClasses.Title}>BazaarPlusPlus</div>,
  content: <PluginPanel />,
  icon: <FaStore />,
  onDismount() {
    console.log("BazaarPlusPlus Decky plugin unloaded");
  },
}));
