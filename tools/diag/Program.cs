// Runs Cpp2IL exactly like BepInEx 6 be.793 does (Il2CppInteropManager.RunCpp2Il), then looks at
// every field/method that carries more than one AddressAttribute / TokenAttribute /
// FieldOffsetAttribute and works out which copy describes THIS build.
using AsmResolver.DotNet;
using AssetRipper.Primitives;
using Cpp2IL.Core;
using Cpp2IL.Core.Api;
using Cpp2IL.Core.InstructionSets;
using Cpp2IL.Core.OutputFormats;
using Cpp2IL.Core.ProcessingLayers;
using LibCpp2IL;

var game = args.Length > 0 ? args[0] : Environment.GetEnvironmentVariable("TAC_GAME") ?? throw new Exception("set TAC_GAME to the game folder");
var gameAssembly = Path.Combine(game, "GameAssembly.dll");
var metadata = Path.Combine(game, @"TagaReconstruction_Data\il2cpp_data\Metadata\global-metadata.dat");

InstructionSetRegistry.RegisterInstructionSet<X86InstructionSet>(DefaultInstructionSets.X86_32);
InstructionSetRegistry.RegisterInstructionSet<X86InstructionSet>(DefaultInstructionSets.X86_64);
LibCpp2IlBinaryRegistry.RegisterBuiltInBinarySupport();
Cpp2IL.Core.Logging.Logger.WarningLog += (m, s) => { };
Cpp2IL.Core.Logging.Logger.InfoLog += (m, s) => { };

Cpp2IlApi.InitializeLibCpp2Il(gameAssembly, metadata, UnityVersion.Parse("6000.3.24f1"), false);
var ctx = Cpp2IlApi.CurrentAppContext;

// True tokens of this build, straight from the metadata: "Namespace.Type::Method" -> tokens
var trueTokens = new Dictionary<string, List<uint>>();
foreach (var asm in ctx.Assemblies)
    foreach (var type in asm.Types)
        foreach (var m in type.Methods)
        {
            if (m.Definition == null) continue;
            var key = $"{type.FullName}::{m.Name}";
            if (!trueTokens.TryGetValue(key, out var l)) trueTokens[key] = l = new List<uint>();
            l.Add(m.Definition.token);
        }

var layers = new List<Cpp2IlProcessingLayer> { new AttributeInjectorProcessingLayer() };
foreach (var l in layers) l.PreProcess(ctx, layers);
foreach (var l in layers) l.Process(ctx);
var assemblies = new AsmResolverDllOutputFormatDefault().BuildAssemblies(ctx);

string[] names = { "AddressAttribute", "TokenAttribute", "FieldOffsetAttribute" };
int dupMembers = 0, tokenChecked = 0, lastIsFresh = 0, lastNotFresh = 0, lastNotFreshShown = 0;
var tokenWinner = new Dictionary<string, int>();   // which copy held the true token
var describe = new Dictionary<string, int>();      // how the copies differ
int printed = 0;

string Where(CustomAttribute a)
{
    var t = a.Constructor?.DeclaringType;
    var scope = t?.Scope?.Name ?? "?";
    return $"{t?.FullName} [scope={scope}, {(t is TypeDefinition ? "defined here" : "reference")}]";
}

string Args(CustomAttribute a) =>
    string.Join(", ", a.Signature?.NamedArguments.Select(n => $"{n.MemberName}={n.Argument.Element}") ?? Enumerable.Empty<string>());

foreach (var asm in assemblies)
    foreach (var type in asm.ManifestModule!.GetAllTypes())
    {
        var members = new List<IHasCustomAttribute>();
        members.AddRange(type.Fields);
        members.AddRange(type.Methods);
        foreach (var member in members)
            foreach (var name in names)
            {
                var hits = member.CustomAttributes
                    .Select((a, i) => (a, i))
                    .Where(x => x.a.Constructor?.DeclaringType?.Name == name).ToList();
                if (hits.Count < 2) continue;
                dupMembers++;
                var lastNs = hits[^1].a.Constructor?.DeclaringType?.Namespace?.ToString();
                var freshCount = hits.Count(h => h.a.Constructor?.DeclaringType?.Namespace?.ToString() == "Cpp2ILInjected");
                if (lastNs == "Cpp2ILInjected" && freshCount == 1) lastIsFresh++;
                else { lastNotFresh++; if (lastNotFreshShown++ < 5) Console.WriteLine($"   LAST-NOT-FRESH: {type.FullName}::{(member as IMemberDefinition)?.Name} {name}: {string.Join(" | ", hits.Select(h => h.a.Constructor?.DeclaringType?.FullName))}"); }
                var key = string.Join(" | ", hits.Select(h => $"#{h.i} {h.a.Constructor?.DeclaringType?.Namespace}@{h.a.Constructor?.DeclaringType?.Scope?.Name}"));
                describe[$"{name}: {key.Replace(member.CustomAttributes.Count.ToString(), "")}"] =
                    describe.GetValueOrDefault($"{name}: {key.Replace(member.CustomAttributes.Count.ToString(), "")}") + 1;

                if (name == "TokenAttribute" && member is MethodDefinition md)
                {
                    var k = $"{type.FullName}::{md.Name}";
                    if (trueTokens.TryGetValue(k, out var toks))
                    {
                        tokenChecked++;
                        for (int c = 0; c < hits.Count; c++)
                        {
                            var v = hits[c].a.Signature?.NamedArguments.FirstOrDefault(n => n.MemberName == "Token")?.Argument.Element?.ToString();
                            if (v != null && toks.Contains(Convert.ToUInt32(v, 16)))
                            {
                                var who = $"copy {c + 1} of {hits.Count} ({Where(hits[c].a)})";
                                tokenWinner[who] = tokenWinner.GetValueOrDefault(who) + 1;
                            }
                        }
                    }
                }

                if (printed < 8)
                {
                    printed++;
                    Console.WriteLine($"--- {asm.Name} {type.FullName} :: {(member as IMemberDefinition)?.Name} ({name})");
                    foreach (var (a, i) in hits)
                        Console.WriteLine($"     attr #{i}: {Where(a)}  {Args(a)}");
                    if (member is MethodDefinition m2 && trueTokens.TryGetValue($"{type.FullName}::{m2.Name}", out var t2))
                        Console.WriteLine($"     true token(s) in this build: {string.Join(",", t2.Select(t => $"0x{t:X}"))}");
                }
            }
    }

Console.WriteLine();
Console.WriteLine($"members with duplicated tags: {dupMembers}");
Console.WriteLine($"  last copy is the single fresh (Cpp2ILInjected) one: {lastIsFresh}; otherwise: {lastNotFresh}");
Console.WriteLine("duplicate patterns (attribute index @ defining scope):");
foreach (var kv in describe.OrderByDescending(k => k.Value).Take(12)) Console.WriteLine($"   {kv.Value,7}  {kv.Key}");
Console.WriteLine($"methods whose token could be checked: {tokenChecked}");
Console.WriteLine("which copy held this build's real token:");
foreach (var kv in tokenWinner.OrderByDescending(k => k.Value)) Console.WriteLine($"   {kv.Value,7}  {kv.Key}");
