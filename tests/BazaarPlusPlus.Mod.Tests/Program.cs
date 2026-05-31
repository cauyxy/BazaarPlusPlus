using System.Collections;
using System.Reflection;

var tests = new (string Name, Action Body)[]
{
    (
        "RefreshFinalBuildsFromRemote accepts metrics v2 rows and matches selected template ids",
        CardSetBuildDataRepositoryTests
            .RefreshFinalBuildsFromRemoteAcceptsMetricsV2RowsAndMatchesSelectedTemplateIds
    ),
    (
        "RefreshFinalBuildsFromRemote keeps legacy final build cache compatibility",
        CardSetBuildDataRepositoryTests.RefreshFinalBuildsFromRemoteKeepsLegacyFinalBuildCacheCompatibility
    ),
    (
        "ResolveConfiguredUrl migrates the old placeholder final builds URL",
        CardSetBuildDataRepositoryTests.ResolveConfiguredUrlMigratesOldPlaceholderFinalBuildsUrl
    ),
    (
        "CardSetPreviewHotkeys maps arrow keys to mode and candidate navigation",
        CardSetPreviewHotkeysTests.MapsArrowKeysToModeAndCandidateNavigation
    ),
};

var failed = 0;
foreach (var test in tests)
{
    try
    {
        test.Body();
        Console.WriteLine($"PASS {test.Name}");
    }
    catch (Exception ex)
    {
        failed++;
        Console.Error.WriteLine($"FAIL {test.Name}");
        Console.Error.WriteLine(ex);
    }
}

return failed == 0 ? 0 : 1;

internal static class CardSetBuildDataRepositoryTests
{
    private const string FirstDooleyItem = "0966f887-5aaf-44a5-90fa-ecb194270513";
    private const string SecondDooleyItem = "1bdbc6f6-2690-445a-877e-90dbbd5e4658";

    public static void RefreshFinalBuildsFromRemoteAcceptsMetricsV2RowsAndMatchesSelectedTemplateIds()
    {
        var repositoryType = LoadRepositoryType();
        var cachePath = Path.Combine(
            Path.GetTempPath(),
            "BazaarPlusPlus.Tests",
            $"{Guid.NewGuid():N}.json"
        );

        InvokePrivateStatic(
            repositoryType,
            "ConfigureFinalBuildRemoteForTests",
            new object?[]
            {
                cachePath,
                new Func<DateTime>(() => new DateTime(2026, 05, 31, 8, 30, 0, DateTimeKind.Utc)),
                new Func<string, string>(_ => MetricsV2Json),
                new Action<Action>(refresh => refresh()),
                new Func<string>(() => "en-US"),
            }
        );

        try
        {
            var refreshArgs = new object?[] { null };
            var refreshSucceeded = (bool)
                InvokePrivateStatic(
                    repositoryType,
                    "TryRefreshFinalBuildsFromRemote",
                    refreshArgs
                )!;

            Assert.True(
                refreshSucceeded,
                $"Expected v2 metrics JSON refresh to succeed, error={refreshArgs[0] ?? "<null>"}"
            );

            var repository = Activator.CreateInstance(repositoryType, nonPublic: true)
                ?? throw new InvalidOperationException("Could not create repository.");
            var selectedTemplateIds = new[]
            {
                Guid.Parse(FirstDooleyItem),
                Guid.Parse(SecondDooleyItem),
            };
            var recommendations = (IEnumerable)
                repositoryType
                    .GetMethod("FindFinalRecommendations", BindingFlags.Instance | BindingFlags.Public)!
                    .Invoke(repository, new object?[] { "Dooley", selectedTemplateIds })!;
            var result = recommendations.Cast<object>().ToArray();

            Assert.Equal(
                2,
                result.Length,
                "Expected two Dooley recommendations containing both selected items."
            );
            Assert.Equal("dooley-rank-1", GetString(result[0], "SetSignature"));
            Assert.Equal("dooley-rank-2", GetString(result[1], "SetSignature"));
            Assert.Equal(0, GetInt(result[0], "ResultIndex"));
            Assert.Equal(2, GetInt(result[0], "ResultCount"));

            var items = ((IEnumerable)GetProperty(result[0], "Items")).Cast<object>().ToArray();
            Assert.Equal(2, items.Length, "Expected the first recommendation to project both v2 items.");
            Assert.Equal(FirstDooleyItem, GetProperty(items[0], "TemplateId").ToString());
            Assert.Equal("Gold", GetProperty(items[0], "Tier").ToString());
            Assert.Equal("Socket_1", GetProperty(items[0], "SocketId").ToString());
            Assert.Equal("Fiery", GetProperty(items[0], "EnchantmentType").ToString());
        }
        finally
        {
            InvokePrivateStatic(repositoryType, "ResetFinalBuildRemoteForTests", Array.Empty<object?>());
            if (File.Exists(cachePath))
                File.Delete(cachePath);
        }
    }

    public static void RefreshFinalBuildsFromRemoteKeepsLegacyFinalBuildCacheCompatibility()
    {
        var repositoryType = LoadRepositoryType();
        var cachePath = Path.Combine(
            Path.GetTempPath(),
            "BazaarPlusPlus.Tests",
            $"{Guid.NewGuid():N}.json"
        );

        InvokePrivateStatic(
            repositoryType,
            "ConfigureFinalBuildRemoteForTests",
            new object?[]
            {
                cachePath,
                new Func<DateTime>(() => new DateTime(2026, 05, 31, 8, 30, 0, DateTimeKind.Utc)),
                new Func<string, string>(_ => LegacyJson),
                new Action<Action>(refresh => refresh()),
                new Func<string>(() => "en-US"),
            }
        );

        try
        {
            var refreshArgs = new object?[] { null };
            var refreshSucceeded = (bool)
                InvokePrivateStatic(
                    repositoryType,
                    "TryRefreshFinalBuildsFromRemote",
                    refreshArgs
                )!;

            Assert.True(
                refreshSucceeded,
                $"Expected legacy final build JSON refresh to succeed, error={refreshArgs[0] ?? "<null>"}"
            );

            var repository = Activator.CreateInstance(repositoryType, nonPublic: true)
                ?? throw new InvalidOperationException("Could not create repository.");
            var selectedTemplateIds = new[]
            {
                Guid.Parse(FirstDooleyItem),
                Guid.Parse(SecondDooleyItem),
            };
            var recommendations = (IEnumerable)
                repositoryType
                    .GetMethod("FindFinalRecommendations", BindingFlags.Instance | BindingFlags.Public)!
                    .Invoke(repository, new object?[] { "Dooley", selectedTemplateIds })!;
            var result = recommendations.Cast<object>().ToArray();

            Assert.Equal(1, result.Length);
            Assert.Equal("legacy-dooley-build", GetString(result[0], "SetSignature"));
        }
        finally
        {
            InvokePrivateStatic(repositoryType, "ResetFinalBuildRemoteForTests", Array.Empty<object?>());
            if (File.Exists(cachePath))
                File.Delete(cachePath);
        }
    }

    public static void ResolveConfiguredUrlMigratesOldPlaceholderFinalBuildsUrl()
    {
        var repositoryType = LoadRepositoryType();
        var resolved = (string)
            InvokePrivateStatic(
                repositoryType,
                "ResolveConfiguredUrl",
                new object?[] { "https://api.example.com/final_builds_for_mod.json" }
            )!;

        Assert.Equal(
            "https://bpp-metrics.bazaarplusplus.com/final_builds/1d/all.json",
            resolved
        );
    }

    private static Type LoadRepositoryType()
    {
        return Type.GetType(
                "BazaarPlusPlus.Game.MonsterPreview.CardSetBuildDataRepository, BazaarPlusPlus",
                throwOnError: true
            )
            ?? throw new InvalidOperationException("Repository type was not found.");
    }

    private static object? InvokePrivateStatic(Type type, string methodName, object?[] args)
    {
        var method = type
            .GetMethods(BindingFlags.Static | BindingFlags.NonPublic | BindingFlags.Public)
            .SingleOrDefault(candidate =>
                candidate.Name == methodName && candidate.GetParameters().Length == args.Length
            );
        if (method == null)
            throw new MissingMethodException(type.FullName, methodName);

        return method.Invoke(null, args);
    }

    private static object GetProperty(object instance, string name)
    {
        return instance
                .GetType()
                .GetProperty(name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)
                ?.GetValue(instance)
            ?? throw new MissingMemberException(instance.GetType().FullName, name);
    }

    private static string GetString(object instance, string name)
    {
        return (string)GetProperty(instance, name);
    }

    private static int GetInt(object instance, string name)
    {
        return (int)GetProperty(instance, name);
    }

    private const string MetricsV2Json =
        """
        {
          "schema_version": "2",
          "rows": [
            {
              "hero": "Dooley",
              "sig": "dooley-rank-2",
              "rank": 2,
              "gold_score": 0.35,
              "run_count": 25,
              "items": [
                {
                  "template_id": "0966F887-5AAF-44A5-90FA-ECB194270513",
                  "socket": 1,
                  "tier": "Gold",
                  "enchant": "Fiery"
                },
                {
                  "template_id": "1BDBC6F6-2690-445A-877E-90DBBD5E4658",
                  "socket": 2,
                  "tier": "Silver",
                  "enchant": ""
                }
              ]
            },
            {
              "hero": "Vanessa",
              "sig": "vanessa-rank-1",
              "rank": 1,
              "gold_score": 0.99,
              "run_count": 99,
              "items": [
                {
                  "template_id": "0966F887-5AAF-44A5-90FA-ECB194270513",
                  "socket": 1,
                  "tier": "Gold"
                },
                {
                  "template_id": "1BDBC6F6-2690-445A-877E-90DBBD5E4658",
                  "socket": 2,
                  "tier": "Silver"
                }
              ]
            },
            {
              "hero": "Dooley",
              "sig": "dooley-missing-selected-item",
              "rank": 3,
              "gold_score": 0.20,
              "run_count": 10,
              "items": [
                {
                  "template_id": "0966f887-5aaf-44a5-90fa-ecb194270513",
                  "socket": 1,
                  "tier": "Gold"
                }
              ]
            },
            {
              "hero": "Dooley",
              "sig": "dooley-rank-1",
              "rank": 1,
              "gold_score": 0.70,
              "run_count": 40,
              "items": [
                {
                  "template_id": "0966f887-5aaf-44a5-90fa-ecb194270513",
                  "socket": 1,
                  "tier": "Gold",
                  "enchant": "Fiery"
                },
                {
                  "template_id": "1bdbc6f6-2690-445a-877e-90dbbd5e4658",
                  "socket": 2,
                  "tier": "Silver"
                }
              ]
            }
          ]
        }
        """;

    private const string LegacyJson =
        """
        {
          "heroes": {
            "Dooley": {
              "distinctBuildCount": 1,
              "includedBuildCount": 1,
              "builds": [
                {
                  "buildId": 0,
                  "cardIds": [
                    "0966f887-5aaf-44a5-90fa-ecb194270513",
                    "1bdbc6f6-2690-445a-877e-90dbbd5e4658"
                  ],
                  "setSignature": "legacy-dooley-build",
                  "goldScore": 3.5,
                  "playerCards": [
                    {
                      "cardId": "0966f887-5aaf-44a5-90fa-ecb194270513",
                      "slot": 1,
                      "tier": 3,
                      "enchant": "Fiery"
                    },
                    {
                      "cardId": "1bdbc6f6-2690-445a-877e-90dbbd5e4658",
                      "slot": 2,
                      "tier": 2
                    }
                  ]
                }
              ],
              "cardIndex": {
                "0966f887-5aaf-44a5-90fa-ecb194270513": [0],
                "1bdbc6f6-2690-445a-877e-90dbbd5e4658": [0]
              },
              "subsetIndex": {
                "0966f887-5aaf-44a5-90fa-ecb194270513|1bdbc6f6-2690-445a-877e-90dbbd5e4658": {
                  "matchedBuildIds": [0]
                }
              }
            }
          }
        }
        """;
}

internal static class Assert
{
    public static void True(bool condition, string message)
    {
        if (!condition)
            throw new InvalidOperationException(message);
    }

    public static void Equal<T>(T expected, T actual, string? message = null)
    {
        if (!EqualityComparer<T>.Default.Equals(expected, actual))
        {
            throw new InvalidOperationException(
                message ?? $"Expected {expected}, got {actual}."
            );
        }
    }
}

internal static class CardSetPreviewHotkeysTests
{
    public static void MapsArrowKeysToModeAndCandidateNavigation()
    {
        var hotkeysType = Type.GetType(
                "BazaarPlusPlus.Game.MonsterPreview.CardSetPreviewHotkeys, BazaarPlusPlus",
                throwOnError: true
            )
            ?? throw new InvalidOperationException("Hotkeys type was not found.");
        var modeType = Type.GetType(
                "BazaarPlusPlus.Game.MonsterPreview.CardSetBuildRecommendationMode, BazaarPlusPlus",
                throwOnError: true
            )
            ?? throw new InvalidOperationException("Mode type was not found.");
        var selectedSet = Enum.Parse(modeType, "SelectedSet");
        var finalBuild = Enum.Parse(modeType, "FinalBuild");

        Assert.Equal(
            selectedSet,
            InvokePrivateStatic(
                hotkeysType,
                "ResolveDisplayMode",
                new object?[] { false, false, true, false }
            )
        );
        Assert.Equal(
            finalBuild,
            InvokePrivateStatic(
                hotkeysType,
                "ResolveDisplayMode",
                new object?[] { false, false, false, true }
            )
        );
        Assert.Equal<object?>(
            null,
            InvokePrivateStatic(
                hotkeysType,
                "ResolveDisplayMode",
                new object?[] { false, false, true, true }
            )
        );

        Assert.Equal(
            -1,
            InvokePrivateStatic(
                hotkeysType,
                "ResolveRecommendationDelta",
                new object?[] { false, false, true, false }
            )
        );
        Assert.Equal(
            1,
            InvokePrivateStatic(
                hotkeysType,
                "ResolveRecommendationDelta",
                new object?[] { false, false, false, true }
            )
        );
        Assert.Equal(
            0,
            InvokePrivateStatic(
                hotkeysType,
                "ResolveRecommendationDelta",
                new object?[] { false, false, true, true }
            )
        );
    }

    private static object? InvokePrivateStatic(Type type, string methodName, object?[] args)
    {
        var method = type
            .GetMethods(BindingFlags.Static | BindingFlags.NonPublic | BindingFlags.Public)
            .SingleOrDefault(candidate =>
                candidate.Name == methodName && candidate.GetParameters().Length == args.Length
            );
        if (method == null)
            throw new MissingMethodException(type.FullName, methodName);

        return method.Invoke(null, args);
    }
}
