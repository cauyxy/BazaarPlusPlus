#nullable enable
using System;
using System.Collections.Generic;
using BazaarGameShared.Domain.Core.Types;
using BazaarPlusPlus.Core.Config;
using BazaarPlusPlus.Core.Events;
using BazaarPlusPlus.Core.GameState;
using BazaarPlusPlus.Core.Paths;
using BazaarPlusPlus.Core.RunContext;
using BepInEx.Logging;

namespace BazaarPlusPlus.Core.Runtime;

internal static class BppRuntimeHost
{
    private static IBppServices? _services;

    public static IBppEventBus EventBus =>
        _services?.EventBus ?? throw CreateNotInstalledException();

    public static ManualLogSource? Logger => _services?.Logger;

    public static IBppConfig Config => _services?.Config ?? throw CreateNotInstalledException();

    public static IPathService Paths => _services?.Paths ?? throw CreateNotInstalledException();

    public static IMonsterCatalog MonsterCatalog =>
        _services?.MonsterCatalog ?? EmptyMonsterCatalog.Instance;

    public static IRunContext RunContext =>
        _services?.RunContext ?? throw CreateNotInstalledException();

    public static IGameStateProbe GameStateProbe =>
        _services?.GameStateProbe ?? throw CreateNotInstalledException();

    public static void Install(IBppServices services)
    {
        _services = services ?? throw new ArgumentNullException(nameof(services));
        BppLog.Info("RuntimeHost", "Installed runtime service bridge");
    }

    public static void Reset()
    {
        _services = null;
    }

    private static InvalidOperationException CreateNotInstalledException()
    {
        return new InvalidOperationException("Runtime services are not installed.");
    }

    private sealed class EmptyMonsterCatalog : IMonsterCatalog
    {
        public static readonly EmptyMonsterCatalog Instance = new();

        public bool TryGetByEncounterId(Guid encounterId, out MonsterInfo? monster)
        {
            monster = null;
            return false;
        }

        public bool TryGetByEncounterId(string encounterId, out MonsterInfo? monster)
        {
            monster = null;
            return false;
        }

        public bool TryGetByEncounterIdPrefix(string encounterIdPrefix, out MonsterInfo? monster)
        {
            monster = null;
            return false;
        }

        public IReadOnlyCollection<MonsterInfo> GetAll()
        {
            return Array.Empty<MonsterInfo>();
        }
    }
}
