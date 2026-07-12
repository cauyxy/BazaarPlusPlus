import { ButtonItem, PanelSection, PanelSectionRow } from "@decky/ui";

import type {
  LatestRelease,
  PluginStatus,
} from "../../decky/backendClient";
import { useInstaller } from "./useInstaller";

function StatusCard({
  status,
  latest,
}: {
  status: PluginStatus | null;
  latest: LatestRelease | null;
}) {
  if (!status) {
    return <div style={{ opacity: 0.7 }}>正在检测…</div>;
  }
  const stateText = !status.game_found
    ? "未找到 Steam 版《The Bazaar》"
    : status.installed
      ? `已安装 ${status.installed_version ?? "未知版本"}`
      : "尚未安装";
  return (
    <div
      style={{
        padding: "10px 12px",
        borderRadius: 8,
        background: "rgba(255,255,255,.08)",
        lineHeight: 1.45,
      }}
    >
      <div>{stateText}</div>
      {latest && <div style={{ opacity: 0.7 }}>最新版：{latest.version}</div>}
      {status.game_path && (
        <div style={{ opacity: 0.55, fontSize: 11, wordBreak: "break-all" }}>
          {status.game_path}
        </div>
      )}
      {status.game_running && (
        <div style={{ color: "#ffc46b" }}>请先退出游戏再执行安装操作。</div>
      )}
    </div>
  );
}

export function PluginPanel() {
  const controller = useInstaller();
  const { status, latest, busy, progress, repairMode } = controller;
  const updateAvailable = latest?.update_available ?? false;
  return (
    <>
      <PanelSection title="Steam Deck 安装状态">
        <PanelSectionRow>
          <StatusCard status={status} latest={latest} />
        </PanelSectionRow>
        {progress && (
          <PanelSectionRow>
            <div style={{ opacity: 0.75 }}>{progress}</div>
          </PanelSectionRow>
        )}
      </PanelSection>
      <PanelSection title="操作">
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            disabled={
              busy ||
              !status?.game_found ||
              status.game_running ||
              Boolean(status?.installed && !updateAvailable)
            }
            onClick={controller.install}
          >
            {busy
              ? "处理中…"
              : updateAvailable
                ? `更新到 ${latest?.version}`
                : "安装 BazaarPlusPlus"}
          </ButtonItem>
        </PanelSectionRow>
        {status?.installed && (
          <>
            <PanelSectionRow>
              <ButtonItem
                layout="below"
                disabled={busy || status.game_running}
                onClick={controller.install}
              >
                重新安装 / 修复
              </ButtonItem>
            </PanelSectionRow>
            <PanelSectionRow>
              <ButtonItem
                layout="below"
                disabled={busy || status.game_running}
                onClick={controller.resetData}
              >
                重置 BazaarPlusPlus 本地数据
              </ButtonItem>
            </PanelSectionRow>
            <PanelSectionRow>
              <ButtonItem
                layout="below"
                disabled={busy || status.game_running}
                onClick={controller.uninstall}
              >
                卸载模组
              </ButtonItem>
            </PanelSectionRow>
          </>
        )}
        {(status?.installed || repairMode !== null) && (
          <PanelSectionRow>
            <ButtonItem
              layout="below"
              disabled={busy || Boolean(status?.game_running)}
              onClick={controller.repairLaunchOptions}
            >
              {repairMode === "restore"
                ? "恢复 Steam 启动参数"
                : "修复 Steam 启动参数"}
            </ButtonItem>
          </PanelSectionRow>
        )}
        <PanelSectionRow>
          <ButtonItem layout="below" disabled={busy} onClick={controller.refresh}>
            刷新状态
          </ButtonItem>
        </PanelSectionRow>
      </PanelSection>
      <PanelSection title="说明">
        <PanelSectionRow>
          <div style={{ fontSize: 12, opacity: 0.7, lineHeight: 1.45 }}>
            首次安装约下载 70 MB。请先启动一次《The Bazaar》并退出，再执行安装。
            模组仍在游戏内运行；本插件只负责 Steam Deck 上的安装、更新和修复。
          </div>
        </PanelSectionRow>
      </PanelSection>
    </>
  );
}
