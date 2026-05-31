#nullable enable

namespace BazaarPlusPlus.Game.MonsterPreview;

internal static class CardSetPreviewHotkeys
{
    public static CardSetBuildRecommendationMode? ResolveDisplayMode(
        bool currentSetPressed,
        bool finalBuildPressed,
        bool previousModePressed,
        bool nextModePressed
    )
    {
        var selectedSetPressed = currentSetPressed || previousModePressed;
        var tenWinBuildPressed = finalBuildPressed || nextModePressed;
        if (selectedSetPressed == tenWinBuildPressed)
            return null;

        return selectedSetPressed
            ? CardSetBuildRecommendationMode.SelectedSet
            : CardSetBuildRecommendationMode.FinalBuild;
    }

    public static int ResolveRecommendationDelta(
        bool previousCandidatePressed,
        bool nextCandidatePressed,
        bool upCandidatePressed,
        bool downCandidatePressed
    )
    {
        var previousPressed = previousCandidatePressed || upCandidatePressed;
        var nextPressed = nextCandidatePressed || downCandidatePressed;
        if (previousPressed == nextPressed)
            return 0;

        return previousPressed ? -1 : 1;
    }
}
