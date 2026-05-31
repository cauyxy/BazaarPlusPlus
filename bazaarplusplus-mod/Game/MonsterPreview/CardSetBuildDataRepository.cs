#nullable enable
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Net.Http;
using System.Reflection;
using System.Threading.Tasks;
using BazaarGameShared.Domain.Cards.Enchantments;
using BazaarGameShared.Domain.Core.Types;
using BazaarPlusPlus.Core.Config;
using BazaarPlusPlus.Game.ItemBoard;
using BazaarPlusPlus.Game.Settings;
using Newtonsoft.Json;
using TheBazaar;

namespace BazaarPlusPlus.Game.MonsterPreview;

internal sealed class CardSetBuildDataRepository
{
    private const string DefaultFinalBuildsRemoteUrl =
        "https://bpp-metrics.bazaarplusplus.com/final_builds/1d/all.json";
    private const string LegacyPlaceholderFinalBuildsRemoteUrl =
        "https://api.example.com/final_builds_for_mod.json";
    private const string FinalBuildsResourceSuffix = "final-builds-top50.json";
    private const string FinalBuildsCacheFileName = "final_builds_v2_1d_all.json";
    private static readonly LocalizedTextSet FinalBuildLabel = new(
        "Ten-Win Build",
        "十胜阵容",
        "十勝陣容",
        "十勝陣容"
    );
    private static readonly TimeSpan FinalBuildsCacheDuration = TimeSpan.FromHours(20);
    private static readonly HttpClient FinalBuildsHttpClient = new()
    {
        Timeout = TimeSpan.FromSeconds(10),
    };
    private static string _finalBuildsRemoteUrl = DefaultFinalBuildsRemoteUrl;
    private static readonly object SyncRoot = new();
    private static FinalBuildRoot? _finalRoot;
    private static bool _attemptedLoad;
    private static string? _finalBuildsCacheFilePath;
    private static Func<DateTime> _utcNow = () => DateTime.UtcNow;
    private static Func<string, string> _downloadFinalBuildJson = DownloadFinalBuildJson;
    private static Action<Action> _queueBackgroundFinalBuildRefresh = QueueBackgroundFinalBuildRefresh;
    private static Func<string> _resolveLanguageCode = ResolveGameLanguageCode;
    private static bool _backgroundFinalBuildRefreshInProgress;

    public bool TryFindFinalRecommendation(
        string? hero,
        IReadOnlyCollection<Guid> templateIds,
        out CardSetBuildRecommendation recommendation
    )
    {
        var recommendations = FindFinalRecommendations(hero, templateIds);
        recommendation = recommendations.FirstOrDefault()!;
        return recommendation != null;
    }

    internal static void Configure(IBppConfig? config)
    {
        _finalBuildsRemoteUrl = ResolveConfiguredUrl(config?.FinalBuildsRemoteUrlConfig?.Value);
    }

    public IReadOnlyList<CardSetBuildRecommendation> FindFinalRecommendations(
        string? hero,
        IReadOnlyCollection<Guid> templateIds
    )
    {
        var finalRoot = EnsureFinalRoot();
        if (finalRoot?.Heroes == null || string.IsNullOrWhiteSpace(hero))
            return Array.Empty<CardSetBuildRecommendation>();

        return finalRoot.Heroes.TryGetValue(hero, out var heroBucket)
            ? FindRecommendations(heroBucket, templateIds, ResolveFinalBuildLabel())
            : Array.Empty<CardSetBuildRecommendation>();
    }

    private static FinalBuildRoot? EnsureFinalRoot()
    {
        EnsureLoaded();
        return _finalRoot;
    }

    private static void EnsureLoaded()
    {
        var shouldRefreshInBackground = false;
        lock (SyncRoot)
        {
            if (_attemptedLoad)
                return;

            _attemptedLoad = true;
            _finalRoot = LoadFinalBuildRoot(out shouldRefreshInBackground);
        }

        if (shouldRefreshInBackground)
            TryQueueFinalBuildRefreshFromRemote("cache_stale_or_missing");
    }

    private static FinalBuildRoot? LoadFinalBuildRoot(out bool shouldRefreshInBackground)
    {
        shouldRefreshInBackground = false;

        if (TryLoadFinalBuildCache(allowExpired: false, out var freshRoot))
            return freshRoot;

        if (TryLoadFinalBuildCache(allowExpired: true, out var staleRoot))
        {
            shouldRefreshInBackground = true;
            BppLog.Info(
                "CardSetBuildDataRepository",
                "Using expired final builds cache; remote refresh was queued in the background."
            );
            return staleRoot;
        }

        shouldRefreshInBackground = true;
        return LoadEmbeddedJson<FinalBuildRoot>(FinalBuildsResourceSuffix);
    }

    internal static bool TryRefreshFinalBuildsFromRemote(out string? error)
    {
        if (!TryLoadRemoteFinalBuilds(out var remoteRoot, out error) || remoteRoot == null)
            return false;

        lock (SyncRoot)
        {
            _finalRoot = remoteRoot;
            _attemptedLoad = true;
        }

        return true;
    }

    private static void TryQueueFinalBuildRefreshFromRemote(string reason)
    {
        if (!TryBeginBackgroundFinalBuildRefresh())
            return;

        try
        {
            _queueBackgroundFinalBuildRefresh(() => RefreshFinalBuildsFromRemoteInBackground(reason));
            BppLog.Info(
                "CardSetBuildDataRepository",
                $"Queued background final builds refresh reason={reason}."
            );
        }
        catch (Exception ex)
        {
            EndBackgroundFinalBuildRefresh();
            BppLog.Warn(
                "CardSetBuildDataRepository",
                $"Failed to queue background final builds refresh reason={reason}: {ex.Message}"
            );
        }
    }

    private static bool TryBeginBackgroundFinalBuildRefresh()
    {
        lock (SyncRoot)
        {
            if (_backgroundFinalBuildRefreshInProgress)
                return false;

            _backgroundFinalBuildRefreshInProgress = true;
            return true;
        }
    }

    private static void EndBackgroundFinalBuildRefresh()
    {
        lock (SyncRoot)
        {
            _backgroundFinalBuildRefreshInProgress = false;
        }
    }

    private static void RefreshFinalBuildsFromRemoteInBackground(string reason)
    {
        try
        {
            if (TryLoadRemoteFinalBuilds(out var remoteRoot, out var error) && remoteRoot != null)
            {
                lock (SyncRoot)
                {
                    _finalRoot = remoteRoot;
                    _attemptedLoad = true;
                }

                BppLog.Info(
                    "CardSetBuildDataRepository",
                    $"Background final builds refresh succeeded reason={reason}."
                );
                return;
            }

            BppLog.Warn(
                "CardSetBuildDataRepository",
                $"Background final builds refresh failed reason={reason} error={error ?? "unknown"}."
            );
        }
        finally
        {
            EndBackgroundFinalBuildRefresh();
        }
    }

    private static bool TryLoadFinalBuildCache(
        bool allowExpired,
        out FinalBuildRoot? finalBuildRoot
    )
    {
        finalBuildRoot = null;

        try
        {
            var cacheFilePath = ResolveFinalBuildsCacheFilePath();
            if (!File.Exists(cacheFilePath))
                return false;

            var lastWriteUtc = File.GetLastWriteTimeUtc(cacheFilePath);
            var expiresAtUtc = lastWriteUtc.Add(FinalBuildsCacheDuration);
            if (!allowExpired && _utcNow() >= expiresAtUtc)
                return false;

            var json = File.ReadAllText(cacheFilePath);
            finalBuildRoot = DeserializeFinalBuildJson(json, "cache");
            if (finalBuildRoot == null)
                return false;

            BppLog.Info(
                "CardSetBuildDataRepository",
                $"Loaded final builds from cache path={cacheFilePath} "
                    + $"expired={_utcNow() >= expiresAtUtc} expiresAtUtc={expiresAtUtc:O}"
            );
            return true;
        }
        catch (Exception ex)
        {
            BppLog.Warn(
                "CardSetBuildDataRepository",
                $"Failed to read final builds cache {ResolveFinalBuildsCacheFilePath()}: {ex.Message}"
            );
            return false;
        }
    }

    private static bool TryLoadRemoteFinalBuilds(out FinalBuildRoot? finalBuildRoot)
    {
        return TryLoadRemoteFinalBuilds(out finalBuildRoot, out _);
    }

    private static bool TryLoadRemoteFinalBuilds(
        out FinalBuildRoot? finalBuildRoot,
        out string? error
    )
    {
        finalBuildRoot = null;
        error = null;

        try
        {
            var json = _downloadFinalBuildJson(_finalBuildsRemoteUrl);
            if (string.IsNullOrWhiteSpace(json))
            {
                error = "empty_response";
                return false;
            }

            finalBuildRoot = DeserializeFinalBuildJson(json, "remote");
            if (finalBuildRoot == null)
            {
                error = "invalid_response";
                return false;
            }

            TryWriteFinalBuildCache(json);
            BppLog.Info(
                "CardSetBuildDataRepository",
                $"Loaded final builds from remote url={_finalBuildsRemoteUrl}"
            );
            return true;
        }
        catch (Exception ex)
        {
            error = ex.Message;
            BppLog.Warn(
                "CardSetBuildDataRepository",
                $"Failed to refresh final builds from {_finalBuildsRemoteUrl}: {ex.Message}"
            );
            return false;
        }
    }

    private static FinalBuildRoot? DeserializeFinalBuildJson(string json, string source)
    {
        try
        {
            var parsed = JsonConvert.DeserializeObject<FinalBuildRoot>(json);
            if (parsed?.Heroes != null)
                return parsed;

            var metricsRoot = JsonConvert.DeserializeObject<MetricsFinalBuildRoot>(json);
            var converted = ConvertMetricsRoot(metricsRoot);
            if (converted?.Heroes == null)
            {
                BppLog.Warn(
                    "CardSetBuildDataRepository",
                    $"Final builds JSON from {source} did not contain a supported final build schema."
                );
                return null;
            }

            return converted;
        }
        catch (Exception ex)
        {
            BppLog.Warn(
                "CardSetBuildDataRepository",
                $"Failed to parse final builds JSON from {source}: {ex.Message}"
            );
            return null;
        }
    }

    private static void TryWriteFinalBuildCache(string json)
    {
        try
        {
            var cacheFilePath = ResolveFinalBuildsCacheFilePath();
            var cacheDirectory = Path.GetDirectoryName(cacheFilePath);
            if (!string.IsNullOrWhiteSpace(cacheDirectory))
                Directory.CreateDirectory(cacheDirectory);

            File.WriteAllText(cacheFilePath, json);
            File.SetLastWriteTimeUtc(cacheFilePath, _utcNow());
        }
        catch (Exception ex)
        {
            BppLog.Warn(
                "CardSetBuildDataRepository",
                $"Failed to write final builds cache {ResolveFinalBuildsCacheFilePath()}: {ex.Message}"
            );
        }
    }

    private static string ResolveConfiguredUrl(string? configuredUrl)
    {
        if (string.IsNullOrWhiteSpace(configuredUrl))
            return DefaultFinalBuildsRemoteUrl;

        if (!Uri.TryCreate(configuredUrl, UriKind.Absolute, out var uri))
            return DefaultFinalBuildsRemoteUrl;

        if (uri.Scheme != Uri.UriSchemeHttps && uri.Scheme != Uri.UriSchemeHttp)
            return DefaultFinalBuildsRemoteUrl;

        var resolved = uri.ToString();
        return string.Equals(
            resolved,
            LegacyPlaceholderFinalBuildsRemoteUrl,
            StringComparison.OrdinalIgnoreCase
        )
            ? DefaultFinalBuildsRemoteUrl
            : resolved;
    }

    private static string ResolveFinalBuildsCacheFilePath()
    {
        return _finalBuildsCacheFilePath
            ?? BuildDefaultFinalBuildsCacheFilePath(BepInEx.Paths.GameRootPath);
    }

    private static string BuildDefaultFinalBuildsCacheFilePath(string gameRootPath)
    {
        return Path.Combine(gameRootPath, "BazaarPlusPlus", FinalBuildsCacheFileName);
    }

    private static string DownloadFinalBuildJson(string url)
    {
        return FinalBuildsHttpClient.GetStringAsync(url).GetAwaiter().GetResult();
    }

    private static void QueueBackgroundFinalBuildRefresh(Action refresh)
    {
        _ = Task.Run(refresh);
    }

    private static void ConfigureFinalBuildRemoteForTests(
        string cacheFilePath,
        Func<DateTime> utcNow,
        Func<string, string> downloadJson
    )
    {
        lock (SyncRoot)
        {
            _finalRoot = null;
            _attemptedLoad = false;
            _backgroundFinalBuildRefreshInProgress = false;
            _finalBuildsCacheFilePath = cacheFilePath;
            _utcNow = utcNow;
            _downloadFinalBuildJson = downloadJson;
            _queueBackgroundFinalBuildRefresh = QueueBackgroundFinalBuildRefresh;
            _resolveLanguageCode = ResolveGameLanguageCode;
        }
    }

    private static void ConfigureFinalBuildRemoteForTests(
        string cacheFilePath,
        Func<DateTime> utcNow,
        Func<string, string> downloadJson,
        Action<Action> queueBackgroundRefresh,
        Func<string> resolveLanguageCode
    )
    {
        lock (SyncRoot)
        {
            _finalRoot = null;
            _attemptedLoad = false;
            _backgroundFinalBuildRefreshInProgress = false;
            _finalBuildsCacheFilePath = cacheFilePath;
            _utcNow = utcNow;
            _downloadFinalBuildJson = downloadJson;
            _queueBackgroundFinalBuildRefresh =
                queueBackgroundRefresh ?? QueueBackgroundFinalBuildRefresh;
            _resolveLanguageCode = resolveLanguageCode ?? ResolveGameLanguageCode;
        }
    }

    private static void ResetFinalBuildRemoteForTests()
    {
        lock (SyncRoot)
        {
            _finalRoot = null;
            _attemptedLoad = false;
            _backgroundFinalBuildRefreshInProgress = false;
            _finalBuildsCacheFilePath = null;
            _utcNow = () => DateTime.UtcNow;
            _downloadFinalBuildJson = DownloadFinalBuildJson;
            _queueBackgroundFinalBuildRefresh = QueueBackgroundFinalBuildRefresh;
            _resolveLanguageCode = ResolveGameLanguageCode;
        }
    }

    private static T? LoadEmbeddedJson<T>(string resourceSuffix)
        where T : class
    {
        try
        {
            var assembly = Assembly.GetExecutingAssembly();
            var resourceName = assembly
                .GetManifestResourceNames()
                .FirstOrDefault(name =>
                    name.EndsWith(resourceSuffix, StringComparison.OrdinalIgnoreCase)
                );
            if (resourceName == null)
            {
                BppLog.Warn(
                    "CardSetBuildDataRepository",
                    $"Embedded resource not found suffix={resourceSuffix}"
                );
                return null;
            }

            using var stream = assembly.GetManifestResourceStream(resourceName);
            if (stream == null)
                return null;

            using var reader = new StreamReader(stream);
            var json = reader.ReadToEnd();
            var parsed = JsonConvert.DeserializeObject<T>(json);
            BppLog.Info(
                "CardSetBuildDataRepository",
                $"Loaded embedded build data resource={resourceName} parsed={(parsed != null)}"
            );
            return parsed;
        }
        catch (Exception ex)
        {
            BppLog.Error(
                "CardSetBuildDataRepository",
                $"Failed to load embedded build data suffix={resourceSuffix}",
                ex
            );
            return null;
        }
    }

    private static IReadOnlyList<CardSetBuildRecommendation> FindRecommendations(
        BuildQueryBucket? bucket,
        IReadOnlyCollection<Guid> templateIds,
        string modeLabel
    )
    {
        if (bucket?.Builds == null || templateIds == null || templateIds.Count == 0)
            return Array.Empty<CardSetBuildRecommendation>();

        var selectedCardIds = templateIds
            .Where(id => id != Guid.Empty)
            .Select(id => id.ToString())
            .Distinct(StringComparer.Ordinal)
            .OrderBy(id => id, StringComparer.Ordinal)
            .ToArray();
        if (selectedCardIds.Length == 0)
            return Array.Empty<CardSetBuildRecommendation>();

        IReadOnlyList<int>? matchedBuildIds = null;
        var preserveIncomingOrder = false;
        if (
            selectedCardIds.Length <= 3
            && bucket.SubsetIndex != null
            && bucket.SubsetIndex.TryGetValue(
                string.Join("|", selectedCardIds),
                out var subsetEntry
            )
            && subsetEntry?.MatchedBuildIds?.Count > 0
        )
        {
            matchedBuildIds = subsetEntry.MatchedBuildIds;
            preserveIncomingOrder = true;
        }
        else if (bucket.CardIndex != null)
        {
            HashSet<int>? intersection = null;
            foreach (var cardId in selectedCardIds)
            {
                if (!bucket.CardIndex.TryGetValue(cardId, out var buildIds) || buildIds.Count == 0)
                    return Array.Empty<CardSetBuildRecommendation>();

                if (intersection == null)
                {
                    intersection = new HashSet<int>(buildIds);
                    continue;
                }

                intersection.IntersectWith(buildIds);
                if (intersection.Count == 0)
                    return Array.Empty<CardSetBuildRecommendation>();
            }

            matchedBuildIds = intersection?.OrderBy(id => id).ToArray();
        }

        if (matchedBuildIds == null || matchedBuildIds.Count == 0)
            return Array.Empty<CardSetBuildRecommendation>();

        var candidates = matchedBuildIds
            .Select(
                (buildId, index) =>
                    new
                    {
                        Build = buildId >= 0 && buildId < bucket.Builds.Count
                            ? bucket.Builds[buildId]
                            : null,
                        BuildId = buildId,
                        OriginalIndex = index,
                    }
            )
            .Where(candidate => candidate.Build?.PlayerCards?.Count > 0)
            .ToList();
        if (candidates.Count == 0)
            return Array.Empty<CardSetBuildRecommendation>();

        var orderedCandidates = preserveIncomingOrder
            ? candidates
            : candidates
                .OrderByDescending(candidate => candidate.Build!.GoldScore)
                .ThenBy(candidate => candidate.BuildId)
                .ToList();

        var recommendations = orderedCandidates
            .Select(
                (candidate, index) =>
                    new CardSetBuildRecommendation
                    {
                        ModeLabel = modeLabel,
                        Source = candidate.Build!.Source ?? string.Empty,
                        SetSignature = candidate.Build!.SetSignature ?? string.Empty,
                        GoldScore = candidate.Build.GoldScore,
                        ResultIndex = index,
                        ResultCount = orderedCandidates.Count,
                        Items = ProjectPlayerCards(candidate.Build.PlayerCards),
                    }
            )
            .Where(recommendation => recommendation.Items.Count > 0)
            .ToArray();
        return recommendations;
    }

    private static IReadOnlyList<ItemBoardItemSpec> ProjectPlayerCards(
        IReadOnlyList<PlayerCardEntry>? playerCards
    )
    {
        if (playerCards == null || playerCards.Count == 0)
            return Array.Empty<ItemBoardItemSpec>();

        return playerCards
            .Where(entry => entry != null && Guid.TryParse(entry.CardId, out _))
            .OrderBy(entry => entry!.Slot)
            .Select(entry =>
            {
                Enum.TryParse<EEnchantmentType>(
                    entry!.Enchant ?? string.Empty,
                    true,
                    out var enchantType
                );
                var hasEnchant =
                    !string.IsNullOrWhiteSpace(entry.Enchant)
                    && !string.Equals(entry.Enchant, "None", StringComparison.OrdinalIgnoreCase);
                return new ItemBoardItemSpec
                {
                    TemplateId = Guid.Parse(entry.CardId!),
                    Tier = !string.IsNullOrWhiteSpace(entry.TierName)
                        ? MapRecommendationTier(entry.TierName)
                        : MapRecommendationTier(entry.Tier),
                    SocketId = entry.Slot.HasValue
                        ? (EContainerSocketId?)Math.Clamp(entry.Slot.Value, 0, 9)
                        : null,
                    EnchantmentType = hasEnchant ? enchantType : null,
                };
            })
            .ToArray();
    }

    private static FinalBuildRoot? ConvertMetricsRoot(MetricsFinalBuildRoot? root)
    {
        if (root?.Rows == null || root.Rows.Count == 0)
            return null;

        var heroes = root
            .Rows.Where(row =>
                row != null
                && !string.IsNullOrWhiteSpace(row.Hero)
                && row.Items != null
                && row.Items.Count > 0
            )
            .GroupBy(row => row.Hero!, StringComparer.OrdinalIgnoreCase)
            .ToDictionary(
                group => group.Key,
                group => BuildBucket(group),
                StringComparer.OrdinalIgnoreCase
            );

        return heroes.Count == 0 ? null : new FinalBuildRoot { Heroes = heroes };
    }

    private static BuildQueryBucket BuildBucket(IEnumerable<MetricsFinalBuildRow> rows)
    {
        var orderedRows = rows
            .OrderBy(row => row.Rank.GetValueOrDefault(int.MaxValue))
            .ThenByDescending(row => row.GoldScore)
            .ThenByDescending(row => row.RunCount)
            .ThenBy(row => row.Signature ?? string.Empty, StringComparer.Ordinal)
            .ToArray();

        var bucket = new BuildQueryBucket();
        var subsetCandidates = new Dictionary<string, List<int>>(StringComparer.Ordinal);

        for (var rowIndex = 0; rowIndex < orderedRows.Length; rowIndex++)
        {
            var row = orderedRows[rowIndex];
            var build = ConvertMetricsRow(row, bucket.Builds.Count);
            if (build.PlayerCards.Count == 0)
                continue;

            var buildId = bucket.Builds.Count;
            bucket.Builds.Add(build);
            foreach (var cardId in build.CardIds)
            {
                if (!bucket.CardIndex.TryGetValue(cardId, out var buildIds))
                {
                    buildIds = new List<int>();
                    bucket.CardIndex[cardId] = buildIds;
                }

                buildIds.Add(buildId);
            }

            AddSubsetCandidates(subsetCandidates, build.CardIds, buildId);
        }

        foreach (var entry in subsetCandidates)
        {
            bucket.SubsetIndex[entry.Key] = new SubsetRecord
            {
                MatchedBuildIds = entry.Value.Distinct().ToList(),
            };
        }

        bucket.DistinctBuildCount = orderedRows.Length;
        bucket.IncludedBuildCount = bucket.Builds.Count;
        return bucket;
    }

    private static BuildRecord ConvertMetricsRow(MetricsFinalBuildRow row, int buildId)
    {
        var cards = row
            .Items.Select(TryNormalizeMetricsItem)
            .Where(item => item != null)
            .Cast<NormalizedMetricsItem>()
            .OrderBy(item => item.Item.Socket ?? item.Item.SlotIndex ?? int.MaxValue)
            .ThenBy(item => item.TemplateId, StringComparer.Ordinal)
            .Select(item => new PlayerCardEntry
            {
                CardId = item.TemplateId,
                Slot = item.Item.Socket ?? item.Item.SlotIndex,
                TierName = item.Item.Tier,
                Enchant = item.Item.Enchant,
            })
            .ToList();
        var cardIds = cards
            .Select(card => card.CardId!)
            .Distinct(StringComparer.Ordinal)
            .OrderBy(cardId => cardId, StringComparer.Ordinal)
            .ToList();

        return new BuildRecord
        {
            BuildId = buildId,
            CardIds = cardIds,
            SetSignature = row.Signature ?? string.Join("|", cardIds),
            Source = "bpp-metrics",
            GoldScore = row.GoldScore,
            Rank = row.Rank,
            RunCount = row.RunCount,
            PlayerCards = cards,
        };
    }

    private static NormalizedMetricsItem? TryNormalizeMetricsItem(MetricsFinalBuildItem? item)
    {
        return item != null && Guid.TryParse(item.TemplateId, out var templateId)
            ? new NormalizedMetricsItem(item, templateId.ToString())
            : null;
    }

    private static void AddSubsetCandidates(
        IDictionary<string, List<int>> subsetCandidates,
        IReadOnlyList<string> cardIds,
        int buildId
    )
    {
        var distinctCardIds = cardIds
            .Distinct(StringComparer.Ordinal)
            .OrderBy(cardId => cardId, StringComparer.Ordinal)
            .ToArray();
        var maxSubsetSize = Math.Min(3, distinctCardIds.Length);
        for (var subsetSize = 1; subsetSize <= maxSubsetSize; subsetSize++)
            AddSubsetCandidates(
                subsetCandidates,
                distinctCardIds,
                subsetSize,
                0,
                new List<string>(),
                buildId
            );
    }

    private static void AddSubsetCandidates(
        IDictionary<string, List<int>> subsetCandidates,
        IReadOnlyList<string> cardIds,
        int subsetSize,
        int startIndex,
        List<string> selected,
        int buildId
    )
    {
        if (selected.Count == subsetSize)
        {
            var key = string.Join("|", selected);
            if (!subsetCandidates.TryGetValue(key, out var buildIds))
            {
                buildIds = new List<int>();
                subsetCandidates[key] = buildIds;
            }

            buildIds.Add(buildId);
            return;
        }

        for (var index = startIndex; index < cardIds.Count; index++)
        {
            selected.Add(cardIds[index]);
            AddSubsetCandidates(
                subsetCandidates,
                cardIds,
                subsetSize,
                index + 1,
                selected,
                buildId
            );
            selected.RemoveAt(selected.Count - 1);
        }
    }

    private static ETier MapRecommendationTier(int? rawTier)
    {
        // Build recommendation JSON stores Bronze..Legendary as 1..5, while ETier is 0..4.
        var normalizedTier = rawTier.GetValueOrDefault();
        if (normalizedTier > 0)
            normalizedTier--;

        normalizedTier = Math.Clamp(normalizedTier, (int)ETier.Bronze, (int)ETier.Legendary);
        return (ETier)normalizedTier;
    }

    private static ETier MapRecommendationTier(string? tierName)
    {
        if (string.IsNullOrWhiteSpace(tierName))
            return ETier.Bronze;

        return tierName.Trim() switch
        {
            "Bronze" => ETier.Bronze,
            "Silver" => ETier.Silver,
            "Gold" => ETier.Gold,
            "Diamond" => ETier.Diamond,
            "Legendary" => ETier.Legendary,
            _ => ETier.Bronze,
        };
    }

    private static string ResolveFinalBuildLabel()
    {
        return FinalBuildLabel.Resolve(_resolveLanguageCode());
    }

    private static string ResolveGameLanguageCode()
    {
        return PlayerPreferences.Data?.LanguageCode ?? string.Empty;
    }

    private sealed class FinalBuildRoot
    {
        [JsonProperty("heroes")]
        public Dictionary<string, BuildQueryBucket>? Heroes { get; set; }
    }

    private sealed class BuildQueryBucket
    {
        [JsonProperty("distinctBuildCount")]
        public int DistinctBuildCount { get; set; }

        [JsonProperty("includedBuildCount")]
        public int IncludedBuildCount { get; set; }

        [JsonProperty("builds")]
        public List<BuildRecord> Builds { get; set; } = new();

        [JsonProperty("cardIndex")]
        public Dictionary<string, List<int>> CardIndex { get; set; } =
            new(StringComparer.Ordinal);

        [JsonProperty("subsetIndex")]
        public Dictionary<string, SubsetRecord> SubsetIndex { get; set; } =
            new(StringComparer.Ordinal);
    }

    private sealed class BuildRecord
    {
        [JsonProperty("buildId")]
        public int BuildId { get; set; }

        [JsonProperty("cardIds")]
        public List<string> CardIds { get; set; } = new();

        [JsonProperty("source")]
        public string? Source { get; set; }

        [JsonProperty("setSignature")]
        public string? SetSignature { get; set; }

        [JsonProperty("goldScore")]
        public double GoldScore { get; set; }

        [JsonProperty("rank")]
        public int? Rank { get; set; }

        [JsonProperty("runCount")]
        public int? RunCount { get; set; }

        [JsonProperty("playerCards")]
        public List<PlayerCardEntry> PlayerCards { get; set; } = new();
    }

    private sealed class SubsetRecord
    {
        [JsonProperty("matchedBuildIds")]
        public List<int> MatchedBuildIds { get; set; } = new();
    }

    private sealed class PlayerCardEntry
    {
        [JsonProperty("cardId")]
        public string? CardId { get; set; }

        [JsonProperty("slot")]
        public int? Slot { get; set; }

        [JsonProperty("tier")]
        public int? Tier { get; set; }

        [JsonProperty("tierName")]
        public string? TierName { get; set; }

        [JsonProperty("enchant")]
        public string? Enchant { get; set; }
    }

    private sealed class MetricsFinalBuildRoot
    {
        [JsonProperty("schema_version")]
        public string? SchemaVersion { get; set; }

        [JsonProperty("rows")]
        public List<MetricsFinalBuildRow> Rows { get; set; } = new();
    }

    private sealed class MetricsFinalBuildRow
    {
        [JsonProperty("hero")]
        public string? Hero { get; set; }

        [JsonProperty("sig")]
        public string? Signature { get; set; }

        [JsonProperty("gold_score")]
        public double GoldScore { get; set; }

        [JsonProperty("rank")]
        public int? Rank { get; set; }

        [JsonProperty("run_count")]
        public int? RunCount { get; set; }

        [JsonProperty("items")]
        public List<MetricsFinalBuildItem> Items { get; set; } = new();
    }

    private sealed class MetricsFinalBuildItem
    {
        [JsonProperty("template_id")]
        public string? TemplateId { get; set; }

        [JsonProperty("socket")]
        public int? Socket { get; set; }

        [JsonProperty("slot_index")]
        public int? SlotIndex { get; set; }

        [JsonProperty("tier")]
        public string? Tier { get; set; }

        [JsonProperty("enchant")]
        public string? Enchant { get; set; }
    }

    private sealed class NormalizedMetricsItem
    {
        public NormalizedMetricsItem(MetricsFinalBuildItem item, string templateId)
        {
            Item = item;
            TemplateId = templateId;
        }

        public MetricsFinalBuildItem Item { get; }

        public string TemplateId { get; }
    }
}
