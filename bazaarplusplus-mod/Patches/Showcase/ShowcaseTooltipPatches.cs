#pragma warning disable CS0436
using BazaarGameClient.Domain.Models.Cards;
using BazaarPlusPlus.Game.MonsterPreview;
using HarmonyLib;
using System.Reflection;
using TheBazaar;
using TheBazaar.UI.Tooltips;
using UnityEngine;

namespace BazaarPlusPlus;

/// <summary>
/// When ShowTooltips runs on a showcase card, set a bypass flag so the
/// tooltip lock check does not block it.
/// </summary>
[HarmonyPatch(typeof(CardController), "ShowTooltips")]
internal static class ShowcaseCardShowTooltipsPatch
{
    [HarmonyPrefix]
    private static void Prefix(CardController __instance)
    {
        if (__instance != null && __instance.GetComponent<ShowcaseCardMarker>() != null)
            ShowcaseTooltipBypass.Active = true;
    }

    [HarmonyPostfix]
    private static void Postfix()
    {
        ShowcaseTooltipBypass.Active = false;
    }
}

/// <summary>
/// While the bypass flag is active, pretend the tooltip controller is not locked.
/// </summary>
[HarmonyPatch(
    typeof(TooltipParentComponent),
    nameof(TooltipParentComponent.IsCardTooltipControllerLocked)
)]
internal static class ShowcaseTooltipLockBypassPatch
{
    [HarmonyPrefix]
    private static bool Prefix(ref bool __result)
    {
        if (!ShowcaseTooltipBypass.Active)
            return true;

        __result = false;
        return false;
    }
}

/// <summary>
/// Track when ShowTooltipController executes for a showcase card so we can
/// prevent DisableLockModeCanvas from tearing down the big-picture lock.
///
/// ShowTooltipController is synchronous and calls DisableLockModeCanvas
/// directly, so a simple flag works reliably here.
/// </summary>
[HarmonyPatch(typeof(CardTooltipController), nameof(CardTooltipController.ShowTooltipController))]
internal static class ShowcaseShowTooltipControllerPatch
{
    [HarmonyPrefix]
    private static void Prefix()
    {
        if (ShowcaseTooltipBypass.Active)
            ShowcaseTooltipBypass.ShowingTooltip = true;
    }

    [HarmonyPostfix]
    private static void Postfix(CardTooltipController __instance)
    {
        if (ShowcaseTooltipBypass.ShowingTooltip)
            ShowcaseTooltipLayering.BringToFront(__instance);

        ShowcaseTooltipBypass.ShowingTooltip = false;
    }
}

/// <summary>
/// Skip DisableLockModeCanvas when showing a tooltip for a showcase card.
/// This keeps the big-picture lock mode canvas (raycast blocking, visuals) intact.
/// </summary>
[HarmonyPatch(typeof(CardTooltipController), "DisableLockModeCanvas")]
internal static class ShowcaseDisableLockCanvasPatch
{
    [HarmonyPrefix]
    private static bool Prefix()
    {
        return !ShowcaseTooltipBypass.ShowingTooltip;
    }
}

[HarmonyPatch(typeof(CardTooltipController), nameof(CardTooltipController.LockTooltipToggle))]
public static class CardTooltipControllerLockTogglePatch
{
    private static readonly PropertyInfo CurrentCardProperty = AccessTools.Property(
        typeof(CardTooltipController),
        "CurrentCard"
    );
    private static readonly FieldInfo CurrentCardField = AccessTools.Field(
        typeof(CardTooltipController),
        "CurrentCard"
    ) ?? AccessTools.Field(typeof(CardTooltipController), "_currentCard");

    [HarmonyPrefix]
    static bool Prefix(CardTooltipController __instance)
    {
        var currentCard = TryGetCurrentCard(__instance);
        if (currentCard == null)
            return true;

        var controller = Data.CardAndSkillLookup?.GetCardController(currentCard);
        if (controller == null || controller.GetComponent<ShowcaseCardMarker>() == null)
            return true;

        BppLog.Debug(
            "EncounterTooltipPreview",
            $"Suppressed lock toggle for showcase card {currentCard.Template?.InternalName ?? currentCard.TemplateId.ToString()}"
        );
        return false;
    }

    private static Card TryGetCurrentCard(CardTooltipController controller)
    {
        if (controller == null)
            return null;

        return CurrentCardProperty?.GetValue(controller) as Card
            ?? CurrentCardField?.GetValue(controller) as Card;
    }
}

internal static class ShowcaseTooltipBypass
{
    /// <summary>
    /// Set during CardController.ShowTooltips() for showcase cards.
    /// Makes IsCardTooltipControllerLocked return false.
    /// </summary>
    public static bool Active;

    /// <summary>
    /// Set during CardTooltipController.ShowTooltipController() when
    /// triggered by a showcase card. Blocks DisableLockModeCanvas.
    /// </summary>
    public static bool ShowingTooltip;
}

internal static class ShowcaseTooltipLayering
{
    private const int MinimumTooltipSortOrder = 100;

    public static void BringToFront(CardTooltipController controller)
    {
        if (controller == null)
            return;

        controller.transform.SetAsLastSibling();

        var maxSortOrder = GetMaxSortOrder(controller);
        var offset = Mathf.Max(0, MinimumTooltipSortOrder - maxSortOrder);

        foreach (var canvas in controller.GetComponentsInChildren<Canvas>(true))
        {
            canvas.overrideSorting = true;
            canvas.sortingOrder += offset;
        }

        foreach (var renderer in controller.GetComponentsInChildren<Renderer>(true))
            renderer.sortingOrder += offset;
    }

    private static int GetMaxSortOrder(CardTooltipController controller)
    {
        var maxSortOrder = 0;

        foreach (var canvas in controller.GetComponentsInChildren<Canvas>(true))
            maxSortOrder = Mathf.Max(maxSortOrder, canvas.sortingOrder);

        foreach (var renderer in controller.GetComponentsInChildren<Renderer>(true))
            maxSortOrder = Mathf.Max(maxSortOrder, renderer.sortingOrder);

        return maxSortOrder;
    }
}
